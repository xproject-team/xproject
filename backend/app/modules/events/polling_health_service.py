"""Slesh polling health lookup for GET /events/{event_id}/polling-health.

slesh_poll_state is scoped by (tenant_id, brand_id, experience_id) — see
app/modules/pos/poll_state_models.py — NOT by event_id; there is no
event_id column or FK on that table. get_or_init_state() and
poll_slesh_for_event() (app/workers/tasks.py) both resolve the scope as
(tenant_id, settings.slesh_brand_id, experience_id=None), so we mirror
that exact scoping here rather than inventing a different lookup.

This means "per event" health is really "per tenant" health today. It's
accurate only because of the enforced one-live-event-per-tenant invariant
(see EventService / cron_auto_transition_event_statuses) — if a tenant
ever runs more than one concurrent live event, this stops being precise
per-event. Flagged for Hesam; not solved here (would require adding
event_id to slesh_poll_state — a bigger schema change, out of scope for
Jul-19).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.events.models import Event
from app.modules.events.polling_health_schemas import PollingHealthResponse
from app.modules.pos.poll_state_models import SleshPollState

_STALE_AFTER_SECONDS = 180
_MAX_CONSECUTIVE_FAILURES = 3


async def get_event_or_none(
    db: AsyncSession, tenant_id: UUID, event_id: UUID,
) -> Event | None:
    return (
        await db.execute(
            select(Event).where(
                Event.tenant_id == tenant_id,
                Event.id == event_id,
            )
        )
    ).scalar_one_or_none()


async def get_polling_health(
    db: AsyncSession, tenant_id: UUID,
) -> PollingHealthResponse | None:
    """Look up the tenant's slesh_poll_state row and compute health.

    Returns None if no poll-state row exists yet (poller has never run
    for this tenant/brand scope) — caller translates that to a 404.
    """
    state = (
        await db.execute(
            select(SleshPollState).where(
                SleshPollState.tenant_id == tenant_id,
                SleshPollState.brand_id == settings.slesh_brand_id,
                SleshPollState.experience_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if state is None:
        return None

    seconds_since_last_run: float | None = None
    if state.last_run_at is not None:
        seconds_since_last_run = (
            datetime.now(timezone.utc) - state.last_run_at
        ).total_seconds()

    is_healthy = (
        seconds_since_last_run is not None
        and seconds_since_last_run < _STALE_AFTER_SECONDS
        and state.consecutive_failures < _MAX_CONSECUTIVE_FAILURES
    )

    return PollingHealthResponse(
        last_run_at=state.last_run_at,
        seconds_since_last_run=seconds_since_last_run,
        last_status=state.last_status,
        last_error=state.last_error,
        consecutive_failures=state.consecutive_failures,
        is_healthy=is_healthy,
    )
