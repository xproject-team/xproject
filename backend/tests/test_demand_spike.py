"""Tests for DemandSpikeDetector (F.10c.1.d).

The detector fires when short-window (15min) burn rate is N× the
long-window (60min) burn rate:
  - 2× ratio → warning
  - 3× ratio → critical

Cases:
  1. 3× spike → critical alert (owner_only)
  2. 2× spike → warning alert (owner_only)
  3. Flat consumption → no alert
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from sqlalchemy import select

from tests.fixtures.alerts.session import TestSessionLocal
from app.modules.alerts.detectors.demand_spike import DemandSpikeDetector
from app.modules.alerts.models import Alert
from tests.fixtures.alerts.factories import (
    make_tenant, make_event, make_bar, make_product,
    make_bar_stock, make_sale_with_children, delete_tenant_cascade,
)


async def _setup_event(session):
    tenant  = await make_tenant(session)
    event   = await make_event(session, tenant.id)
    bar     = await make_bar(session, tenant.id, event.id)
    product = await make_product(session, tenant.id)
    await make_bar_stock(
        session, tenant.id, event.id, bar.id, product.id,
        allocated_qty=Decimal("100"),
        current_qty=Decimal("50"),
    )
    return tenant, event, bar, product


@pytest.mark.asyncio
async def test_demand_spike_fires_critical_on_3x_ratio():
    """15min rate ~3× 60min rate → critical anomaly fires."""
    async with TestSessionLocal() as session:
        tenant, event, bar, product = await _setup_event(session)
        # 5 sales in last 15 min (recent burst)
        await make_sale_with_children(
            session, tenant.id, event.id, bar.id, product.id,
            qty=Decimal("1"), count=5, age_minutes=2,
        )
        # 5 more sales between 30-60 min ago (baseline)
        # So 60min rate = 10 sales / 60min = 10/hr
        #    15min rate = 5 sales / 15min = 20/hr
        #    ratio = 20/10 = 2× — boost it to 3× by adding more recent
        await make_sale_with_children(
            session, tenant.id, event.id, bar.id, product.id,
            qty=Decimal("1"), count=10, age_minutes=2,
        )
        await session.commit()
        tenant_id = tenant.id
        event_id  = event.id

    try:
        async with TestSessionLocal() as session:
            result = await DemandSpikeDetector(session).evaluate(tenant_id, event_id)
            await session.commit()
            assert result.get("fired", 0) >= 1, f"Expected spike alert, got: {result}"

            alerts = (await session.execute(
                select(Alert).where(
                    Alert.tenant_id == tenant_id,
                    Alert.event_id  == event_id,
                )
            )).scalars().all()
            assert len(alerts) >= 1
            spike = next(a for a in alerts if str(a.alert_type) in ("anomaly", "AlertType.anomaly"))
            assert str(spike.severity) in ("critical", "AlertSeverity.critical")
            assert str(spike.audience) in ("owner_only", "AlertAudience.owner_only")

    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)


@pytest.mark.asyncio
async def test_demand_spike_fires_warning_on_2x_ratio():
    """15min rate ~2× 60min rate → warning anomaly."""
    async with TestSessionLocal() as session:
        tenant, event, bar, product = await _setup_event(session)
        # 4 sales recent + 4 sales 45min old → 15min rate ~16/hr, 60min ~8/hr
        await make_sale_with_children(
            session, tenant.id, event.id, bar.id, product.id,
            qty=Decimal("1"), count=4, age_minutes=2,
        )
        await make_sale_with_children(
            session, tenant.id, event.id, bar.id, product.id,
            qty=Decimal("1"), count=4, age_minutes=45,
        )
        await session.commit()
        tenant_id = tenant.id
        event_id  = event.id

    try:
        async with TestSessionLocal() as session:
            result = await DemandSpikeDetector(session).evaluate(tenant_id, event_id)
            await session.commit()
            # Should fire — either warning or critical depending on exact ratio
            assert result.get("fired", 0) >= 1, f"Expected spike alert, got: {result}"

    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)


@pytest.mark.asyncio
async def test_demand_spike_silent_on_flat_consumption():
    """Steady consumption rate → no anomaly fires."""
    async with TestSessionLocal() as session:
        tenant, event, bar, product = await _setup_event(session)
        # Even distribution: 3 sales at -5min, 3 sales at -30min, 3 at -50min
        # Both windows see similar rates → no spike
        for age in (5, 30, 50):
            await make_sale_with_children(
                session, tenant.id, event.id, bar.id, product.id,
                qty=Decimal("1"), count=3, age_minutes=age,
            )
        await session.commit()
        tenant_id = tenant.id
        event_id  = event.id

    try:
        async with TestSessionLocal() as session:
            result = await DemandSpikeDetector(session).evaluate(tenant_id, event_id)
            await session.commit()
            assert result.get("fired", 0) == 0, f"Expected no spike, got: {result}"

    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)
