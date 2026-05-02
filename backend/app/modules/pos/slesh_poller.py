"""Slesh order polling worker — the heart of the Slesh integration.

Composes everything from B1-B6 into a single cycle that:

  1. Loads the cursor for (tenant, brand, experience) from slesh_poll_state
  2. Computes the [since_ts, until_ts] window with 60-second overlap
  3. Streams orders from Slesh via SleshAdapter.list_orders()
  4. Hands each order to ingest_order() -> StockTransactionService.ingest_sale()
  5. Updates the cursor on success, records the failure on error
  6. Returns a structured PollResult — no exceptions escape the function

This file is ENVIRONMENT-AGNOSTIC. It runs:
  - From the arq scheduler (cron_jobs in scheduler.py — wired in B6.6)
  - From the manual trigger CLI (B6.6 — for ops + dev)
  - From the historical backfill CLI (B7 — same logic, different window)

DESIGN CHOICES (locked in B6):

- Single-scope per call. Each call polls ONE (tenant, brand, experience).
  Multi-tenant iteration lives in the cron entry point (future), not here.

- Defaults from settings. The function takes explicit args; callers from
  the cron pull defaults from `settings.slesh_*`.

- Atomic per call. We open ONE async session and ONE adapter for the
  whole poll, commit at the end. Catastrophic failure rolls everything
  back — no partial cursor advances.

- Never raise. PollResult.status tells the caller (cron / CLI) what
  happened. arq tasks must not raise (per scheduler.py convention).

Spec: docs/slesh-integration-roadmap.md §B6.5
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config              import settings
from app.core.database            import AsyncSessionLocal
from app.modules.stock_transactions.service import StockTransactionService

from app.modules.pos.adapters.slesh import SleshAdapter
from app.modules.pos.order_ingester import IngestResult, ingest_order
from app.modules.pos.poll_state     import (
    PollWindow, get_or_init_state, compute_window,
    record_success, record_failure,
)
from app.modules.pos.poll_state_models import SleshPollState
from app.modules.pos.retry          import CircuitBreakerOpen

if TYPE_CHECKING:
    from app.modules.pos.schemas import Order

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Result type — what the cron entry point and CLI both consume
# ─────────────────────────────────────────────────────────────────────
@dataclass
class PollResult:
    """Outcome of a single poll cycle for one (tenant, brand, experience)."""
    status:           str             = "ok"        # ok | error | circuit_open | no_event
    window:           PollWindow | None = None
    orders_seen:      int             = 0
    orders_ingested:  int             = 0
    lines_ingested:   int             = 0
    lines_replayed:   int             = 0
    lines_skipped:    int             = 0
    lines_errors:     int             = 0
    new_high_water_ts: int | None     = None
    error_msg:        str             = ""
    per_order_results: list[IngestResult] = field(default_factory=list)

    def __str__(self) -> str:
        if self.status != "ok":
            return f"PollResult(status={self.status} error={self.error_msg[:80]!r})"
        return (
            f"status=ok orders_seen={self.orders_seen} "
            f"orders_ingested={self.orders_ingested} "
            f"lines={self.lines_ingested} replayed={self.lines_replayed} "
            f"skipped={self.lines_skipped} errors={self.lines_errors}"
        )


# ─────────────────────────────────────────────────────────────────────
# Public API — single poll cycle for one scope
# ─────────────────────────────────────────────────────────────────────
async def poll_slesh_orders(
    *,
    tenant_id:     UUID,
    event_id:      UUID,
    brand_id:      str | None = None,
    experience_id: str | None = None,
    until_ts:      datetime | None = None,
) -> PollResult:
    """Run one poll cycle. Catches all exceptions; returns PollResult.

    Args:
        tenant_id:     Which tenant to scope writes to.
        event_id:      Which XProject event to attach transactions to. Bars
                       and orders are validated against this event.
        brand_id:      Slesh brand to query. Defaults to settings.slesh_brand_id.
        experience_id: Optional Slesh experience filter (None == brand-wide).
        until_ts:      Upper bound of the poll window. Defaults to now (UTC).

    Returns:
        PollResult with status + per-order details.
    """
    brand_id = brand_id or settings.slesh_brand_id
    if not brand_id:
        return PollResult(
            status="error",
            error_msg="No brand_id available (param=None and settings.slesh_brand_id is empty).",
        )

    result = PollResult()

    async with AsyncSessionLocal() as db:
        # ─── 1. Load / init the cursor row ───────────────────────────
        state = await get_or_init_state(
            db=db,
            tenant_id=tenant_id,
            brand_id=brand_id,
            experience_id=experience_id,
            anchor_ts=until_ts,    # for backfill: anchor lookback to caller's window upper bound
        )

        # ─── 2. Compute the [since, until] window with overlap ───────
        window = compute_window(state, until_ts=until_ts)
        result.window = window
        logger.info(
            "poll_slesh_orders: tenant=%s brand=%s exp=%s window=[%s -> %s] (%.0fs)",
            tenant_id, brand_id, experience_id,
            window.since_ts.isoformat(), window.until_ts.isoformat(),
            window.width_seconds,
        )

        # ─── 3. Open the adapter, stream + ingest ────────────────────
        try:
            await _stream_and_ingest(
                db=db,
                window=window,
                tenant_id=tenant_id,
                event_id=event_id,
                brand_id=brand_id,
                experience_id=experience_id,
                result=result,
            )

        except CircuitBreakerOpen as exc:
            # Adapter circuit is open — short-circuit fast. Cursor is NOT
            # advanced; next cycle will retry.
            await record_failure(
                db=db, state=state,
                status="circuit_open",
                error_msg=str(exc),
            )
            await db.commit()
            result.status    = "circuit_open"
            result.error_msg = str(exc)
            logger.warning("poll_slesh_orders: circuit open, skipping cycle: %s", exc)
            return result

        except Exception as exc:    # noqa: BLE001 — never let the worker raise
            # Any other failure (network, parse, DB). Cursor is NOT advanced.
            await record_failure(
                db=db, state=state,
                status="error",
                error_msg=f"{type(exc).__name__}: {exc}",
            )
            await db.commit()
            result.status    = "error"
            result.error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception("poll_slesh_orders: unexpected failure")
            return result

        # ─── 4. Success path — advance the cursor atomically ─────────
        await record_success(
            db=db, state=state,
            new_high_water_ts=result.new_high_water_ts,
        )
        await db.commit()
        logger.info("poll_slesh_orders: %s", result)
        return result


# ─────────────────────────────────────────────────────────────────────
# Internal: stream from adapter + dispatch to ingester
# ─────────────────────────────────────────────────────────────────────
async def _stream_and_ingest(
    *,
    db:            AsyncSession,
    window:        PollWindow,
    tenant_id:     UUID,
    event_id:      UUID,
    brand_id:      str,
    experience_id: str | None,
    result:        PollResult,
) -> None:
    """Open the adapter, iterate orders, ingest each one. Mutates result."""
    # StockTransactionService takes the db session directly and
    # constructs its repository dependencies internally. See
    # app/modules/stock_transactions/service.py __init__.
    txn_service = StockTransactionService(db)

    async with SleshAdapter(
        token              = settings.slesh_api_token,
        brand_id           = brand_id,
        base_url           = settings.slesh_base_url,
        request_timeout    = settings.slesh_request_timeout,
        rate_limit_rps     = settings.slesh_rate_limit_rps,
        max_retries        = settings.slesh_max_retries,
    ) as adapter:

        async for order in adapter.list_orders(
            since_ts      = window.since_ts,
            until_ts      = window.until_ts,
            experience_id = experience_id,
        ):
            result.orders_seen += 1

            ingest = await ingest_order(
                db        = db,
                order     = order,
                event_id  = event_id,
                tenant_id = tenant_id,
                service   = txn_service,
            )
            result.per_order_results.append(ingest)

            # Aggregate per-line counters
            result.lines_ingested  += ingest.lines_ingested
            result.lines_replayed  += ingest.lines_replayed
            result.lines_skipped   += ingest.lines_skipped
            result.lines_errors    += ingest.lines_errors

            if ingest.lines_ingested > 0 or ingest.lines_replayed > 0:
                result.orders_ingested += 1

            # Update high-water mark to the most recent order seen.
            # _createdAt is Unix ms in the Slesh schema.
            if (result.new_high_water_ts is None
                or order.created_at > result.new_high_water_ts):
                result.new_high_water_ts = order.created_at


__all__ = ["PollResult", "poll_slesh_orders"]
