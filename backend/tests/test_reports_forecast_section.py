"""Tests for ReportAggregator._build_forecast_accuracy (Section B).

Needs a trained ModelArtifact (via retrain_demand_model) — kept separate
from test_reports_extended_sections.py because of that heavier fixture.
Mirrors the fixture pattern in test_demand_loader.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.modules.customer_analytics.models import CustomerPurchase
from app.modules.events.models import Event, EventStatus
from app.modules.predictions.demand import loader as loader_module
from app.modules.predictions.demand.retrain import retrain_demand_model
from app.modules.reports.aggregator import ReportAggregator
from tests.fixtures.alerts.factories import delete_tenant_cascade, make_event, make_product, make_tenant
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clear_loader_cache():
    loader_module._cache.clear()
    yield
    loader_module._cache.clear()


async def _complete_event(session, event: Event, *, hours_ago: int = 10) -> Event:
    started = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    ended = datetime.now(timezone.utc) - timedelta(hours=hours_ago - 8)
    await session.execute(
        update(Event)
        .where(Event.id == event.id)
        .values(status=EventStatus.COMPLETED, started_at=started, ended_at=ended)
    )
    await session.flush()
    await session.refresh(event)
    return event


async def _purchase(session, tenant_id, event_id, product_id, *, hour_offset, category, qty=1):
    ordered_at = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=hour_offset)
    p = CustomerPurchase(
        tenant_id=tenant_id, event_id=event_id, customer_key=f"cust-{hour_offset}-{category}",
        slesh_order_id=f"order-{hour_offset}-{category}-{qty}", product_id=product_id,
        product_name="Test Drink", category=category, qty=Decimal(str(qty)),
        price_cents=1000, is_deposit=False, ordered_at=ordered_at,
    )
    session.add(p)
    await session.flush()
    return p


async def test_forecast_accuracy_unavailable_when_no_model_trained():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        await _complete_event(session, event)

        fc = await ReportAggregator(session)._build_forecast_accuracy(tenant.id, event.id)
        assert fc.available is False
        assert fc.unavailable_reason is not None

        await delete_tenant_cascade(session, tenant.id)


async def test_forecast_accuracy_unavailable_without_purchase_data(tmp_path):
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        await retrain_demand_model(session, tenant.id, triggered_by="test", artifacts_dir=tmp_path)
        event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        await _complete_event(session, event)

        fc = await ReportAggregator(session)._build_forecast_accuracy(tenant.id, event.id)
        assert fc.available is False

        await delete_tenant_cascade(session, tenant.id)


async def test_forecast_accuracy_builds_hourly_band_and_consistent_hit_count(tmp_path):
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        await retrain_demand_model(session, tenant.id, triggered_by="test", artifacts_dir=tmp_path)
        event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        await _complete_event(session, event)
        product = await make_product(session, tenant.id, name="Spritz")

        # Spread purchases across several hours so multiple HOUR_GRID
        # checkpoints have real actuals to compare against.
        total_qty = 0
        for hour in range(0, 6):
            qty = 10 + hour
            await _purchase(session, tenant.id, event.id, product.id, hour_offset=hour, category="spritz", qty=qty)
            total_qty += qty

        fc = await ReportAggregator(session)._build_forecast_accuracy(tenant.id, event.id)

        assert fc.available is True
        assert fc.predicted_final_total is not None
        assert fc.actual_final_total == pytest.approx(float(total_qty), abs=0.01)
        assert len(fc.hours) > 0
        assert fc.band_hours_total == len(fc.hours)
        assert fc.band_hits == sum(1 for h in fc.hours if h.within_band)
        for h in fc.hours:
            assert h.lower <= h.upper
            assert h.within_band == (h.lower <= h.actual <= h.upper)

        await delete_tenant_cascade(session, tenant.id)
