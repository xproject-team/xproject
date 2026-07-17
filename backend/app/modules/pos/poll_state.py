"""Polling cursor management — tracks how far the Slesh poller has caught up.

Uses the `slesh_poll_state` table (added in migration m1_add_slesh_poll_state)
to persist the high-water mark across worker restarts.

THE OVERLAP-WINDOW STRATEGY (Resilience Pattern P1):
We always ask Slesh for orders since `last_seen_ts - 60s`, not since
`last_seen_ts` itself. This catches near-boundary orders that race with
our poll. Duplicates are filtered by the stock_transactions unique
constraint on (tenant, source, source_idempotency_key) — so a 60-second
re-fetch is safe.

Without this overlap, an order created exactly at our last poll's end
boundary could be missed forever. With this overlap, every order is
guaranteed to be re-fetched at least once before its window closes.

Spec: docs/slesh-integration-roadmap.md §B6.4
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pos.converters import datetime_to_unix_ms

logger = logging.getLogger(__name__)


# Default lookback when no cursor exists yet — first-ever poll for a scope
# fetches the last hour of orders so we don't suddenly try to ingest 38k
# historical rows on initial deployment.
_FIRST_POLL_LOOKBACK_MINUTES = 60

# Overlap on every subsequent poll. 60 seconds is enough to absorb any
# realistic clock skew between our worker and Slesh's load balancer.
_OVERLAP_SECONDS = 60


# ─────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────
@dataclass
class PollWindow:
    """The (since_ts, until_ts) span the worker should ask Slesh for next."""
    since_ts: datetime          # tz-aware, UTC
    until_ts: datetime          # tz-aware, UTC

    @property
    def width_seconds(self) -> float:
        return (self.until_ts - self.since_ts).total_seconds()


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────
async def get_or_init_state(
    *,
    db:            AsyncSession,
    tenant_id:     UUID,
    brand_id:      str,
    experience_id: str | None = None,
    anchor_ts:     datetime | None = None,
) -> "SleshPollState":
    """Fetch the cursor row for this scope; create it if missing.

    The first time the poller fires for a (tenant, brand, experience) tuple,
    we initialise `last_seen_ts` to `now - _FIRST_POLL_LOOKBACK_MINUTES`.
    This avoids a surprise 38k-row historical ingest on the very first run.
    """
    # Late import to avoid circular references through the models module
    from app.modules.pos.poll_state_models import SleshPollState

    stmt = (
        select(SleshPollState)
        .where(SleshPollState.tenant_id     == tenant_id)
        .where(SleshPollState.brand_id      == brand_id)
        .where(SleshPollState.experience_id == experience_id)
        .limit(1)
    )
    res     = await db.execute(stmt)
    state   = res.scalar_one_or_none()

    if state is not None:
        return state

    # First poll for this scope — initialise with a recent lookback
    # anchored to caller-supplied time (for backfill) or now (live polling).
    anchor = anchor_ts if anchor_ts is not None else datetime.now(tz=timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    initial_ts = int(
        (anchor - timedelta(minutes=_FIRST_POLL_LOOKBACK_MINUTES)).timestamp() * 1000
    )
    state = SleshPollState(
        tenant_id     = tenant_id,
        brand_id      = brand_id,
        experience_id = experience_id,
        last_seen_ts  = initial_ts,
    )
    db.add(state)
    await db.flush()
    logger.info(
        "poll_state: initialised new cursor for tenant=%s brand=%s exp=%s "
        "with %d-minute lookback",
        tenant_id, brand_id, experience_id, _FIRST_POLL_LOOKBACK_MINUTES,
    )
    return state


def compute_window(
    state: "SleshPollState",
    *,
    until_ts: datetime | None = None,
    overlap_seconds: int = _OVERLAP_SECONDS,
) -> PollWindow:
    """Compute the next poll's [since_ts, until_ts] span.

    Args:
        state:           Current SleshPollState row.
        until_ts:        Upper bound. None -> now (UTC).
        overlap_seconds: How far back of the cursor to re-fetch for boundary safety.

    Returns:
        PollWindow with tz-aware UTC datetimes.
    """
    if until_ts is None:
        until_ts = datetime.now(tz=timezone.utc)
    elif until_ts.tzinfo is None:
        until_ts = until_ts.replace(tzinfo=timezone.utc)

    cursor_dt = datetime.fromtimestamp(state.last_seen_ts / 1000, tz=timezone.utc)
    since_ts  = cursor_dt - timedelta(seconds=overlap_seconds)

    # Guard: never let the window go negative (clock-skew sanity)
    if since_ts > until_ts:
        since_ts = until_ts - timedelta(seconds=overlap_seconds)

    return PollWindow(since_ts=since_ts, until_ts=until_ts)


async def record_success(
    *,
    db:                  AsyncSession,
    state:               "SleshPollState",
    new_high_water_ts:   int | None,
) -> None:
    """Update the cursor after a successful poll cycle.

    Args:
        new_high_water_ts: Unix ms of the most recent order we successfully
                           ingested. None means 'no orders in this window' —
                           we still mark last_run_at so ops can see the poller
                           is alive.
    """
    state.last_run_at = datetime.now(tz=timezone.utc)
    state.last_status = "ok"
    state.last_error  = None
    state.consecutive_failures = 0
    if new_high_water_ts is not None and new_high_water_ts > state.last_seen_ts:
        state.last_seen_ts = new_high_water_ts
    await db.flush()


async def record_failure(
    *,
    db:           AsyncSession,
    state:        "SleshPollState",
    status:       str,                  # "error" | "circuit_open"
    error_msg:    str,
) -> None:
    """Update bookkeeping after a failed poll cycle. Cursor is NOT advanced."""
    state.last_run_at = datetime.now(tz=timezone.utc)
    state.last_status = status[:32]
    # Truncate error message — long Pydantic errors can be huge
    state.last_error  = error_msg[:2000]
    state.consecutive_failures = (state.consecutive_failures or 0) + 1
    await db.flush()



def explicit_window(
    since_ts: datetime,
    until_ts: datetime,
) -> PollWindow:
    """Construct a PollWindow with explicit bounds, bypassing the cursor.

    Used by historical backfill: each chunk has deterministic bounds, so
    cursor-derived overlap windows would just cause idempotency replays
    on already-ingested orders.
    """
    if since_ts.tzinfo is None:
        since_ts = since_ts.replace(tzinfo=timezone.utc)
    if until_ts.tzinfo is None:
        until_ts = until_ts.replace(tzinfo=timezone.utc)
    if since_ts >= until_ts:
        raise ValueError(f"since_ts ({since_ts}) must be < until_ts ({until_ts})")
    return PollWindow(since_ts=since_ts, until_ts=until_ts)


__all__ = [
    "PollWindow",
    "get_or_init_state",
    "compute_window",
    "explicit_window",
    "record_success",
    "record_failure",
]
