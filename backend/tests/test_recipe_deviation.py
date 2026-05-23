"""Tests for RecipeDeviationDetector (F.10c.1.e).

Algorithm: |actual - expected| / expected → deviation ratio
  - >= 0.20 → warning
  - >= 0.40 → critical

Cases:
  1. +40% over-pour → critical (owner_only)
  2. +25% over-pour → warning
  3. Within 10% → no alert
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from sqlalchemy import select

from tests.fixtures.alerts.session import TestSessionLocal
from app.modules.alerts.detectors.recipe_deviation import RecipeDeviationDetector
from app.modules.alerts.models import Alert
from app.modules.products.models import ProductUnit, ProductType
from app.modules.stock_transactions.models import TransactionSource
from tests.fixtures.alerts.factories import (
    make_tenant, make_event, make_bar, make_product, make_bar_stock,
    make_recipe, make_recipe_item, make_stock_transaction,
    delete_tenant_cascade,
)


async def _setup_recipe(session):
    """Setup: tenant + event + bar + drink + ingredient + recipe (50ml/drink)."""
    tenant   = await make_tenant(session)
    event    = await make_event(session, tenant.id)
    bar      = await make_bar(session, tenant.id, event.id)
    drink    = await make_product(session, tenant.id, unit=ProductUnit.GLASS,
                                   product_type=ProductType.DRINK)
    rum      = await make_product(session, tenant.id, unit=ProductUnit.ML,
                                   product_type=ProductType.INGREDIENT)
    await make_bar_stock(
        session, tenant.id, event.id, bar.id, drink.id,
        allocated_qty=Decimal("100"), current_qty=Decimal("80"),
    )
    await make_bar_stock(
        session, tenant.id, event.id, bar.id, rum.id,
        allocated_qty=Decimal("5000"), current_qty=Decimal("4000"),
    )
    recipe = await make_recipe(session, tenant.id, drink.id,
                                yield_qty=Decimal("1"), yield_unit=ProductUnit.GLASS)
    await make_recipe_item(session, tenant.id, recipe.id, rum.id,
                            qty=Decimal("50"), unit=ProductUnit.ML)
    return tenant, event, bar, drink, rum


async def _record_drink_sale_with_deviation(
    session, tenant_id, event_id, bar_id, drink_id, rum_id,
    *, drinks_sold: int, actual_rum_per_drink: Decimal,
):
    """Simulate `drinks_sold` cocktails, with actual rum consumption per drink."""
    for _ in range(drinks_sold):
        # Parent: drink sale (parent_transaction_id IS NULL)
        parent = await make_stock_transaction(
            session, tenant_id, event_id, bar_id, drink_id,
            qty=Decimal("1"), source=TransactionSource.SLESH_POS,
        )
        # Child: rum consumption (parent_transaction_id = parent.id)
        await make_stock_transaction(
            session, tenant_id, event_id, bar_id, rum_id,
            qty=actual_rum_per_drink,
            source=TransactionSource.SLESH_POS,
            parent_transaction_id=parent.id,
        )


@pytest.mark.asyncio
async def test_recipe_deviation_fires_critical_on_40pct_overpour():
    """10 drinks sold → expected 500ml rum, actual 700ml = 40% over → critical."""
    async with TestSessionLocal() as session:
        tenant, event, bar, drink, rum = await _setup_recipe(session)
        await _record_drink_sale_with_deviation(
            session, tenant.id, event.id, bar.id, drink.id, rum.id,
            drinks_sold=10, actual_rum_per_drink=Decimal("70"),  # 700ml actual
        )
        await session.commit()
        tenant_id, event_id, bar_id, rum_id = tenant.id, event.id, bar.id, rum.id

    try:
        async with TestSessionLocal() as session:
            result = await RecipeDeviationDetector(session).evaluate(tenant_id, event_id)
            await session.commit()
            assert result.get("fired", 0) >= 1, f"Expected critical deviation, got: {result}"

            alerts = (await session.execute(
                select(Alert).where(Alert.tenant_id == tenant_id)
            )).scalars().all()
            deviation_alerts = [
                a for a in alerts
                if "deviation" in str(a.alert_type).lower() or "anomaly" in str(a.alert_type).lower()
            ]
            assert len(deviation_alerts) >= 1
            crit = next((a for a in deviation_alerts if "critical" in str(a.severity).lower()), None)
            assert crit is not None, f"Expected critical, got: {[(str(a.alert_type), str(a.severity)) for a in deviation_alerts]}"
            assert str(crit.audience) in ("owner_only", "AlertAudience.owner_only")

    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)


@pytest.mark.asyncio
async def test_recipe_deviation_fires_warning_on_25pct_overpour():
    """10 drinks → expected 500ml, actual 625ml = 25% over → warning."""
    async with TestSessionLocal() as session:
        tenant, event, bar, drink, rum = await _setup_recipe(session)
        await _record_drink_sale_with_deviation(
            session, tenant.id, event.id, bar.id, drink.id, rum.id,
            drinks_sold=10, actual_rum_per_drink=Decimal("62.5"),
        )
        await session.commit()
        tenant_id, event_id = tenant.id, event.id

    try:
        async with TestSessionLocal() as session:
            result = await RecipeDeviationDetector(session).evaluate(tenant_id, event_id)
            await session.commit()
            assert result.get("fired", 0) >= 1, f"Expected warning deviation, got: {result}"

    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)


@pytest.mark.asyncio
async def test_recipe_deviation_silent_when_within_threshold():
    """10 drinks → expected 500ml, actual 510ml = 2% deviation → no alert."""
    async with TestSessionLocal() as session:
        tenant, event, bar, drink, rum = await _setup_recipe(session)
        await _record_drink_sale_with_deviation(
            session, tenant.id, event.id, bar.id, drink.id, rum.id,
            drinks_sold=10, actual_rum_per_drink=Decimal("51"),
        )
        await session.commit()
        tenant_id, event_id = tenant.id, event.id

    try:
        async with TestSessionLocal() as session:
            result = await RecipeDeviationDetector(session).evaluate(tenant_id, event_id)
            await session.commit()
            assert result.get("fired", 0) == 0, f"Expected no alert, got: {result}"

    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)
