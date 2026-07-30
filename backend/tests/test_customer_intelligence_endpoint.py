"""Tests for GET /api/v1/events/{event_id}/customer-intelligence and
POST /api/v1/events/{event_id}/hot-night-override.

Uses the isolated_client + db_session fixtures (SAVEPOINT rollback,
never mutates xproject_dev) — same pattern as
test_revenue_forecast_endpoint.py. Deep service-layer coverage (guest
segmentation, returning guests, forecast integration) lives in
test_customer_intelligence.py; these are the HTTP-boundary smoke tests
(auth, tenant isolation, status codes, response shape).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Tenant
from app.modules.events.models import Event, EventStatus
from app.modules.venues.models import Venue


async def _get_tenant(db: AsyncSession) -> Tenant:
    r = await db.execute(select(Tenant).where(Tenant.slug == "noma-group"))
    return r.scalar_one()


async def _create_venue(db: AsyncSession, tenant_id) -> Venue:
    v = Venue(tenant_id=tenant_id, name=f"Test Venue {uuid4().hex[:8]}", address="Test address")
    db.add(v)
    await db.flush()
    return v


async def _create_event(db: AsyncSession, tenant_id, venue_id, status=EventStatus.DRAFT) -> Event:
    ev = Event(
        tenant_id=tenant_id, venue_id=venue_id, name=f"Test Event {uuid4().hex[:8]}",
        scheduled_at=datetime(2026, 8, 2, 18, 0, tzinfo=timezone.utc),
        scheduled_end_at=datetime(2026, 8, 3, 4, 0, tzinfo=timezone.utc),
        status=status, expected_guest_count=1000, version=1,
    )
    db.add(ev)
    await db.flush()
    return ev


async def _login(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": "omar@nomagroup.it", "password": "xproject2026"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, f"login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_customer_intelligence_before_doors_open(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    await db_session.flush()

    headers = await _login(isolated_client)
    as_of = datetime(2026, 8, 2, 18, 0, tzinfo=timezone.utc)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/customer-intelligence",
        params={"as_of_time": as_of.isoformat()},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["hour_offset_from_start"] is None
    assert data["guests"]["live_identified_count"] == 0
    assert data["demand_forecast"]["available"] is False
    assert data["predicted_vs_actual"] == []
    assert data["hot_night_override"] is False


@pytest.mark.asyncio
async def test_customer_intelligence_404_unknown_event(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    headers = await _login(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{uuid4()}/customer-intelligence", headers=headers,
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error"] == "event_not_found"


@pytest.mark.asyncio
async def test_customer_intelligence_respects_tenant_isolation(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    other_tenant = Tenant(name=f"other-tenant-{uuid4().hex[:8]}", slug=uuid4().hex[:12])
    db_session.add(other_tenant)
    await db_session.flush()
    venue = await _create_venue(db_session, other_tenant.id)
    event = await _create_event(db_session, other_tenant.id, venue.id)
    await db_session.flush()

    headers = await _login(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/customer-intelligence", headers=headers,
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "event_not_in_tenant"


@pytest.mark.asyncio
async def test_hot_night_override_round_trip(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    await db_session.flush()

    headers = await _login(isolated_client)

    r = await isolated_client.post(
        f"/api/v1/events/{event.id}/hot-night-override",
        json={"enabled": True}, headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["hot_night_override"] is True

    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/customer-intelligence",
        params={"as_of_time": datetime(2026, 8, 2, 18, 0, tzinfo=timezone.utc).isoformat()},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["hot_night_override"] is True

    r = await isolated_client.post(
        f"/api/v1/events/{event.id}/hot-night-override",
        json={"enabled": False}, headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["hot_night_override"] is False


@pytest.mark.asyncio
async def test_hot_night_override_404_unknown_event(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    headers = await _login(isolated_client)
    r = await isolated_client.post(
        f"/api/v1/events/{uuid4()}/hot-night-override",
        json={"enabled": True}, headers=headers,
    )
    assert r.status_code == 404, r.text
