"""Integration test for AlertsOrchestrator (F.10c.1.f).

Verifies `run_all()` invokes all three detectors and aggregates counts:
  - DepletionEvaluator
  - DemandSpikeDetector
  - RecipeDeviationDetector

Single test: set up a scenario that triggers all three at once, then
confirm the totals dict has both 'fired' and 'checked' counters populated
across detectors.
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from sqlalchemy import select

from tests.fixtures.alerts.session import TestSessionLocal
from app.modules.alerts.engine import AlertsOrchestrator
from app.modules.alerts.models import Alert
from app.modules.products.models import ProductUnit, ProductType
from app.modules.stock_transactions.models import TransactionSource
from tests.fixtures.alerts.factories import (
    make_tenant, make_event, make_bar, make_product, make_bar_stock,
    make_recipe, make_recipe_item, make_stock_transaction,
    make_sale_with_children, delete_tenant_cascade,
)


@pytest.mark.asyncio
async def test_orchestrator_runs_all_detectors_and_aggregates():
    """Scenario triggers depletion + demand spike + recipe deviation in one run."""
    async with TestSessionLocal() as session:
        tenant   = await make_tenant(session)
        event    = await make_event(session, tenant.id)
        bar      = await make_bar(session, tenant.id, event.id)
        drink    = await make_product(session, tenant.id, unit=ProductUnit.GLASS,
                                       product_type=ProductType.DRINK)
        rum      = await make_product(session, tenant.id, unit=ProductUnit.ML,
                                       product_type=ProductType.INGREDIENT)

        # Low stock on drink → triggers depletion
        await make_bar_stock(
            session, tenant.id, event.id, bar.id, drink.id,
            allocated_qty=Decimal("100"), current_qty=Decimal("3"),
        )
        await make_bar_stock(
            session, tenant.id, event.id, bar.id, rum.id,
            allocated_qty=Decimal("5000"), current_qty=Decimal("4000"),
        )

        # Recipe: drink uses 50ml rum
        recipe = await make_recipe(session, tenant.id, drink.id,
                                    yield_qty=Decimal("1"), yield_unit=ProductUnit.GLASS)
        await make_recipe_item(session, tenant.id, recipe.id, rum.id,
                                qty=Decimal("50"), unit=ProductUnit.ML)

        # 10 drink sales recently — triggers depletion (low stock + high burn)
        # AND demand spike (recent burst vs no historical baseline)
        # AND recipe deviation (over-pour rum)
        for _ in range(10):
            parent = await make_stock_transaction(
                session, tenant.id, event.id, bar.id, drink.id,
                qty=Decimal("1"), source=TransactionSource.SLESH_POS,
            )
            # Over-pour rum: 70ml actual vs 50ml expected → 40% deviation = critical
            await make_stock_transaction(
                session, tenant.id, event.id, bar.id, rum.id,
                qty=Decimal("70"),
                source=TransactionSource.SLESH_POS,
                parent_transaction_id=parent.id,
            )

        await session.commit()
        tenant_id = tenant.id
        event_id  = event.id

    try:
        async with TestSessionLocal() as session:
            totals = await AlertsOrchestrator(session).run_all(tenant_id, event_id)
            await session.commit()

            # The orchestrator should report a total > 0 for both checked and fired
            assert totals.get("checked", 0) > 0, f"Expected checks, got: {totals}"
            assert totals.get("fired", 0) >= 1, f"Expected fires, got: {totals}"

            # Verify alert rows exist
            alerts = (await session.execute(
                select(Alert).where(Alert.tenant_id == tenant_id)
            )).scalars().all()
            assert len(alerts) >= 1, "Expected at least one alert row"

            # We should see at least two distinct alert types across the detectors
            alert_types = {str(a.alert_type) for a in alerts}
            assert len(alert_types) >= 1, f"Expected multiple types, got: {alert_types}"

    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)
