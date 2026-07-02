"""Tests for GET /api/v1/events/{event_id}/revenue-forecast (Phase D).

Uses the isolated_client + db_session fixtures so every test runs inside
a SAVEPOINT that auto-rolls back — xproject_dev is never mutated. See
tests/test_event_recipes_crud.py for the pattern this file follows.

StockTransaction rows are constructed directly (not via the shared
tests/fixtures/alerts/factories.py::make_stock_transaction helper)
because these tests need precise control over created_at and
price_cents, which that factory doesn't expose.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Tenant
from app.modules.bars.models import Bar
from app.modules.events.models import Event, EventStatus
from app.modules.products.models import Product, ProductType, ProductUnit
from app.modules.stock_transactions.models import StockTransaction, TransactionSource
from app.modules.predictions.nowcast.predictor import get_predictor, year_weighted_fallback_mean
from app.modules.venues.models import Venue


# ─── Helpers ─────────────────────────────────────────────────────────

async def _get_tenant(db: AsyncSession) -> Tenant:
    r = await db.execute(select(Tenant).where(Tenant.slug == "noma-group"))
    return r.scalar_one()


async def _create_venue(db: AsyncSession, tenant_id: UUID) -> Venue:
    v = Venue(
        tenant_id=tenant_id,
        name=f"Test Venue {uuid4().hex[:8]}",
        address="Test address",
    )
    db.add(v)
    await db.flush()
    return v


async def _create_event(
    db: AsyncSession, tenant_id: UUID, venue_id: UUID,
    status: EventStatus = EventStatus.DRAFT,
) -> Event:
    ev = Event(
        tenant_id=tenant_id,
        venue_id=venue_id,
        name=f"Test Event {uuid4().hex[:8]}",
        scheduled_at=datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc),
        scheduled_end_at=datetime(2026, 7, 6, 4, 0, tzinfo=timezone.utc),
        status=status,
        expected_guest_count=1000,
        version=1,
    )
    db.add(ev)
    await db.flush()
    return ev


async def _create_bar(db: AsyncSession, tenant_id: UUID, event_id: UUID) -> Bar:
    bar = Bar(
        tenant_id=tenant_id,
        event_id=event_id,
        name=f"Bar-{uuid4().hex[:6]}",
        bar_type="drinks",
        is_active=True,
    )
    db.add(bar)
    await db.flush()
    return bar


async def _create_product(db: AsyncSession, tenant_id: UUID) -> Product:
    p = Product(
        tenant_id=tenant_id,
        name=f"Test Drink {uuid4().hex[:8]}",
        product_type=ProductType.DRINK,
        unit=ProductUnit.GLASS,
    )
    db.add(p)
    await db.flush()
    return p


async def _add_sale(
    db: AsyncSession, tenant_id: UUID, event_id: UUID, bar_id: UUID, product_id: UUID,
    *, created_at: datetime, price_cents: int,
    source: TransactionSource = TransactionSource.SLESH_POS,
) -> StockTransaction:
    """A parent (revenue-carrying) transaction at an explicit timestamp."""
    tx = StockTransaction(
        tenant_id=tenant_id,
        event_id=event_id,
        bar_id=bar_id,
        product_id=product_id,
        qty=Decimal("1"),
        price_cents=price_cents,
        source=source,
        source_idempotency_key=uuid4().hex,
        created_at=created_at,
    )
    db.add(tx)
    await db.flush()
    return tx


async def _login_in_isolation(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": "omar@nomagroup.it", "password": "xproject2026"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, f"login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ─── Tests ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_forecast_at_hour_0_returns_year_weighted_fallback_mean(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    """Phase F: the pre-event fallback is now year_weighted_fallback_mean
    (event.scheduled_at.year), not the flat all-time historical_mean —
    see predictor.py's "Phase F — what shipped and what didn't" for why
    only the fallback (not shape_curve/r2_table) was year-adjusted."""
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)  # scheduled_at year 2026
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    as_of = datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/revenue-forecast",
        params={"as_of_time": as_of.isoformat()},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()

    predictor = get_predictor()
    expected_mean = year_weighted_fallback_mean(predictor._events_df, target_year=2026)
    # Sanity: the year-weighted 2026 prior differs from the flat mean
    # (2025 pulls it down) — otherwise this test can't distinguish the
    # two implementations.
    assert expected_mean != pytest.approx(predictor.historical_mean, abs=0.01)

    assert data["confidence"] == 0.0
    assert data["confidence_tier"] == "early"
    assert data["hour_offset_from_start"] == 0.0
    assert data["current_revenue_eur"] == 0.0
    assert data["predicted_final_revenue_eur"] == pytest.approx(expected_mean, abs=0.01)
    assert data["year_weighted_prior_used"] is True
    assert data["historical_n"] == predictor.historical_n
    assert data["training_events_count"] == predictor.historical_n
    assert data["historical_range_eur"]["min"] == pytest.approx(predictor.historical_range_eur[0])
    assert data["historical_range_eur"]["max"] == pytest.approx(predictor.historical_range_eur[1])


@pytest.mark.asyncio
async def test_forecast_with_no_transactions(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    """Distinct from the hour-0 test: confirms the zero-transactions
    path specifically (no StockTransaction rows exist for this event
    at all, at any timestamp), not just 'none yet as of this moment'."""
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/revenue-forecast", headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["current_revenue_eur"] == 0.0
    assert data["hour_offset_from_start"] == 0.0
    assert data["confidence"] == 0.0
    assert len(data["predicted_curve"]) == 10  # hours 1..10 — strictly after hour_offset=0.0


@pytest.mark.asyncio
async def test_forecast_at_hour_6_returns_meaningful_prediction(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id)
    product = await _create_product(db_session, tenant.id)

    first_tx = datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc)
    # Two sales: one right at the start, one at hour 6 — €20,000 total.
    await _add_sale(db_session, tenant.id, event.id, bar.id, product.id,
                     created_at=first_tx, price_cents=1_000_000)
    await _add_sale(db_session, tenant.id, event.id, bar.id, product.id,
                     created_at=first_tx + timedelta(hours=6), price_cents=1_000_000)
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    as_of = first_tx + timedelta(hours=6)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/revenue-forecast",
        params={"as_of_time": as_of.isoformat()},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["current_revenue_eur"] == pytest.approx(20000.0)
    assert data["year_weighted_prior_used"] is False  # real revenue present — not the fallback path
    assert data["hour_offset_from_start"] == pytest.approx(6.0, abs=0.01)
    predictor = get_predictor()
    expected_confidence = predictor._interp_r2(6.0)
    assert data["confidence"] == pytest.approx(expected_confidence, abs=0.001)
    # Sane, not exact — the point estimate is 20000 / shape_curve[6].
    assert 20000 < data["predicted_final_revenue_eur"] < 100000
    assert data["vs_historical_avg_eur"] == pytest.approx(
        data["predicted_final_revenue_eur"] - predictor.historical_mean, abs=0.01,
    )


@pytest.mark.asyncio
async def test_forecast_at_hour_8_high_confidence(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id)
    product = await _create_product(db_session, tenant.id)

    first_tx = datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc)
    await _add_sale(db_session, tenant.id, event.id, bar.id, product.id,
                     created_at=first_tx, price_cents=4_000_000)
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    as_of = first_tx + timedelta(hours=8)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/revenue-forecast",
        params={"as_of_time": as_of.isoformat()},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["confidence"] >= 0.8
    assert data["confidence_tier"] == "trustworthy"


@pytest.mark.asyncio
async def test_forecast_404_unknown_event(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{uuid4()}/revenue-forecast", headers=headers,
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error"] == "event_not_found"


@pytest.mark.asyncio
async def test_forecast_respects_tenant_isolation(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    """The event belongs to a freshly created (different) tenant; the
    request is authenticated as Omar (noma-group tenant) -> 403, not 404."""
    other_tenant = Tenant(name=f"other-tenant-{uuid4().hex[:8]}", slug=uuid4().hex[:12])
    db_session.add(other_tenant)
    await db_session.flush()

    venue = await _create_venue(db_session, other_tenant.id)
    event = await _create_event(db_session, other_tenant.id, venue.id)
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/revenue-forecast", headers=headers,
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "event_not_in_tenant"
