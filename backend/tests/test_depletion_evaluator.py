"""Tests for DepletionEvaluator (F.10c.1.c).

Three cases:
  1. Low stock + active burn rate  → fires critical alert
  2. Healthy stock                 → fires nothing
  3. Stock replenished after alert → auto-resolves existing alert
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from sqlalchemy import select

from tests.fixtures.alerts.session import TestSessionLocal
from app.modules.alerts.engine import DepletionEvaluator
from app.modules.alerts.models import Alert
from tests.fixtures.alerts.factories import (
    make_tenant, make_event, make_bar, make_product,
    make_bar_stock, make_sale_with_children, delete_tenant_cascade,
)


@pytest.mark.asyncio
async def test_depletion_fires_critical_on_low_stock():
    """Bar has 3 bottles left, high burn rate → critical alert fires."""
    async with TestSessionLocal() as session:
        tenant  = await make_tenant(session)
        event   = await make_event(session, tenant.id)
        bar     = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id)
        await make_bar_stock(
            session, tenant.id, event.id, bar.id, product.id,
            allocated_qty=Decimal("100"),
            current_qty=Decimal("3"),
        )
        await make_sale_with_children(
            session, tenant.id, event.id, bar.id, product.id,
            qty=Decimal("1"), count=10,
        )
        await session.commit()
        tenant_id  = tenant.id
        event_id   = event.id
        bar_id     = bar.id
        product_id = product.id

    try:
        # evaluate + verify in one session so the committed alert is visible
        async with TestSessionLocal() as session:
            result = await DepletionEvaluator(session).evaluate(tenant_id, event_id)
            assert result.get("fired", 0) >= 1, f"Expected alert to fire, got: {result}"
            await session.commit()
            alerts = (await session.execute(
                select(Alert).where(
                    Alert.tenant_id == tenant_id,
                    Alert.event_id  == event_id,
                )
            )).scalars().all()
            assert len(alerts) >= 1
            alert = alerts[0]
            assert str(alert.severity)   in ("critical", "AlertSeverity.critical")
            assert str(alert.alert_type) in ("depletion", "AlertType.depletion")
            assert alert.bar_id           == bar_id
            assert alert.product_id       == product_id

    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)


@pytest.mark.asyncio
async def test_depletion_silent_on_healthy_stock():
    """Bar has 90 bottles, low burn rate → no alert fires."""
    async with TestSessionLocal() as session:
        tenant  = await make_tenant(session)
        event   = await make_event(session, tenant.id)
        bar     = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id)
        await make_bar_stock(
            session, tenant.id, event.id, bar.id, product.id,
            allocated_qty=Decimal("100"),
            current_qty=Decimal("90"),
        )
        await make_sale_with_children(
            session, tenant.id, event.id, bar.id, product.id,
            qty=Decimal("1"), count=1,
        )
        await session.commit()
        tenant_id = tenant.id
        event_id  = event.id

    try:
        async with TestSessionLocal() as session:
            result = await DepletionEvaluator(session).evaluate(tenant_id, event_id)
            assert result.get("fired", 0) == 0, f"Expected no alert, got: {result}"
            alerts = (await session.execute(
                select(Alert).where(
                    Alert.tenant_id == tenant_id,
                    Alert.event_id  == event_id,
                )
            )).scalars().all()
            assert len(alerts) == 0

    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)


@pytest.mark.asyncio
async def test_depletion_auto_resolves_when_restocked():
    """Alert fires on low stock, stock replenished → alert auto-resolves."""
    from sqlalchemy import update
    from app.modules.bar_stock.models import BarStock

    async with TestSessionLocal() as session:
        tenant  = await make_tenant(session)
        event   = await make_event(session, tenant.id)
        bar     = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id)
        await make_bar_stock(
            session, tenant.id, event.id, bar.id, product.id,
            allocated_qty=Decimal("100"),
            current_qty=Decimal("3"),
        )
        await make_sale_with_children(
            session, tenant.id, event.id, bar.id, product.id,
            qty=Decimal("1"), count=10,
        )
        await session.commit()
        tenant_id  = tenant.id
        event_id   = event.id
        bar_id     = bar.id
        product_id = product.id

    try:
        # First pass — alert fires
        async with TestSessionLocal() as session:
            await DepletionEvaluator(session).evaluate(tenant_id, event_id)

        # Restock
        async with TestSessionLocal() as session:
            await session.execute(
                update(BarStock)
                .where(
                    BarStock.tenant_id  == tenant_id,
                    BarStock.event_id   == event_id,
                    BarStock.bar_id     == bar_id,
                    BarStock.product_id == product_id,
                )
                .values(current_qty=Decimal("80"))
            )
            await session.commit()

        # Second pass — alert should auto-resolve
        async with TestSessionLocal() as session:
            await DepletionEvaluator(session).evaluate(tenant_id, event_id)
            await session.flush()
            alerts = (await session.execute(
                select(Alert).where(
                    Alert.tenant_id == tenant_id,
                    Alert.event_id  == event_id,
                )
            )).scalars().all()
            unresolved = [a for a in alerts if a.lifecycle_state.value == "active"]
            assert len(unresolved) == 0, f"Expected resolved, found active: {unresolved}"

    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)
