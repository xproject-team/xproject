"""Tests for GET /events/{event_id}/polling-health (Day 4, Jul-19 sprint).

Uses isolated_client + db_session (SAVEPOINT rollback), the same pattern
as tests/test_event_recipes_crud.py. Every mutation here — including the
temporary UPDATE/DELETE against the real noma-group slesh_poll_state
row — rolls back at test end; xproject_dev's real polling state is
untouched once each test finishes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.auth.models import Tenant
from app.modules.events.models import Event, EventStatus
from app.modules.pos.poll_state_models import SleshPollState
from app.modules.venues.models import Venue


async def _get_tenant(db: AsyncSession) -> Tenant:
    r = await db.execute(select(Tenant).where(Tenant.slug == "noma-group"))
    return r.scalar_one()


async def _get_or_make_event(db: AsyncSession, tenant_id: UUID) -> Event:
    """The endpoint only needs an event that belongs to this tenant — it
    doesn't care about status. Reuse an existing one if present rather
    than assuming seed data; create one (+ a venue) if the tenant has
    none."""
    existing = (await db.execute(
        select(Event).where(Event.tenant_id == tenant_id).limit(1)
    )).scalars().first()
    if existing is not None:
        return existing

    venue = (await db.execute(
        select(Venue).where(Venue.tenant_id == tenant_id).limit(1)
    )).scalars().first()
    if venue is None:
        venue = Venue(
            tenant_id=tenant_id,
            name=f"polling-health-test-venue-{uuid4().hex[:8]}",
            address="Test address",
        )
        db.add(venue)
        await db.flush()

    event = Event(
        tenant_id=tenant_id,
        venue_id=venue.id,
        name=f"polling-health-test-event-{uuid4().hex[:8]}",
        status=EventStatus.LIVE,
        expected_guest_count=100,
        scheduled_at=datetime.now(timezone.utc),
        scheduled_end_at=datetime.now(timezone.utc) + timedelta(hours=4),
        version=1,
    )
    db.add(event)
    await db.flush()
    return event


async def _get_poll_state(db: AsyncSession, tenant_id: UUID) -> SleshPollState | None:
    return (await db.execute(
        select(SleshPollState).where(
            SleshPollState.tenant_id == tenant_id,
            SleshPollState.brand_id == settings.slesh_brand_id,
            SleshPollState.experience_id.is_(None),
        )
    )).scalar_one_or_none()


async def _make_poll_state(db: AsyncSession, tenant_id: UUID) -> SleshPollState:
    state = SleshPollState(
        tenant_id=tenant_id,
        brand_id=settings.slesh_brand_id,
        experience_id=None,
        last_seen_ts=0,
    )
    db.add(state)
    await db.flush()
    return state


async def _login_in_isolation(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": "omar@nomagroup.it", "password": "xproject2026"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, f"login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_polling_health_endpoint_returns_healthy(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    event = await _get_or_make_event(db_session, tenant.id)

    state = await _get_poll_state(db_session, tenant.id) or await _make_poll_state(db_session, tenant.id)
    state.last_run_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    state.last_status = "ok"
    state.last_error = None
    state.consecutive_failures = 0
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/polling-health", headers=headers,
    )

    assert r.status_code == 200
    body = r.json()
    assert body["is_healthy"] is True
    assert body["seconds_since_last_run"] < 180
    assert body["consecutive_failures"] == 0
    assert body["last_status"] == "ok"


@pytest.mark.asyncio
async def test_polling_health_endpoint_returns_stalled(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    event = await _get_or_make_event(db_session, tenant.id)

    state = await _get_poll_state(db_session, tenant.id) or await _make_poll_state(db_session, tenant.id)
    state.last_run_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    state.last_status = "error"
    state.last_error = "circuit open"
    state.consecutive_failures = 5
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/polling-health", headers=headers,
    )

    assert r.status_code == 200
    body = r.json()
    assert body["is_healthy"] is False
    assert body["seconds_since_last_run"] >= 180
    assert body["consecutive_failures"] == 5


@pytest.mark.asyncio
async def test_polling_health_endpoint_returns_404_when_missing(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    event = await _get_or_make_event(db_session, tenant.id)

    # Remove the poll-state row for this scope inside the SAVEPOINT — it
    # rolls back automatically at test end, restoring the real row.
    await db_session.execute(
        delete(SleshPollState).where(
            SleshPollState.tenant_id == tenant.id,
            SleshPollState.brand_id == settings.slesh_brand_id,
            SleshPollState.experience_id.is_(None),
        )
    )
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/polling-health", headers=headers,
    )

    assert r.status_code == 404
    assert r.json()["detail"] == "No polling state for this event"
