"""Tests for compute_bar_supplier_stock's Day 3 cutover from the free-text
slesh_category ↔ product.name join to the product_id FK (migration aa5,
backfill script app/scripts/backfill_recipe_product_id.py).

Root cause of the Sundance Jul-5 depletion outage: slesh_category and
product.name were two independently maintained string namespaces that
silently drifted apart, zeroing out consumed_ml for hours. These tests
reproduce that exact mismatch (slesh_category='SPRITZ ARANCIO' vs.
product.name='Sprtiz') and prove the cascade now works via product_id.

Day 2.5 adds tests for the backfill script's drink-over-supply preference
rule (app/scripts/backfill_recipe_product_id.py) — production dry-run
found 44 "ambiguous" rows that were always a drink/supply pair sharing a
name; the fix prefers the drink candidate instead of skipping to triage.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import delete

from app.modules.bars.models import Bar
from app.modules.event_storage.bar_supplier_stock_service import (
    compute_bar_supplier_stock,
)
from app.modules.event_storage.models import EventCategoryIngredient, SupplierProduct
from app.modules.event_storage.models import EventStockBarAllocation
from app.modules.products.models import Product, ProductCategory, ProductType, ProductUnit
from app.modules.stock_transactions.models import TransactionSource
from app.scripts.backfill_recipe_product_id import BackfillSummary, _backfill_tenant
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_event,
    make_stock_transaction,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


# ─── Helpers ─────────────────────────────────────────────────────────

async def _make_bar(session, tenant_id: UUID, event_id: UUID, *, name: str = "Main Bar") -> Bar:
    bar = Bar(
        tenant_id=tenant_id,
        event_id=event_id,
        name=name,
        bar_type="drinks",
        is_active=True,
    )
    session.add(bar)
    await session.flush()
    return bar


async def _make_product(
    session, tenant_id: UUID, *, name: str, product_type: ProductType = ProductType.DRINK,
) -> Product:
    p = Product(
        tenant_id=tenant_id,
        name=name,
        product_type=product_type,
        category=ProductCategory.PREMIUM_COCKTAIL if product_type == ProductType.DRINK else None,
        unit=ProductUnit.GLASS,
        default_price_cents=1000,
        is_archived=False,
    )
    session.add(p)
    await session.flush()
    return p


async def _make_supplier_product(session, tenant_id: UUID) -> SupplierProduct:
    sp = SupplierProduct(
        tenant_id=tenant_id,
        supplier_name="Partesa",
        supplier_sku="1LT-APEROL",
        item_name="APEROL BARBIERI 1LT",
        category="aperitivo",
        default_unit="BO",
        units_per_pack=1,
        volume_per_unit_ml=1000,
    )
    session.add(sp)
    await session.flush()
    return sp


async def _make_recipe_rule(
    session, tenant_id: UUID, event_id: UUID,
    product_id: UUID, supplier_product_id: UUID, *,
    slesh_category: str,
    ml_per_sale: Decimal = Decimal("60"),
) -> EventCategoryIngredient:
    rule = EventCategoryIngredient(
        tenant_id=tenant_id,
        event_id=event_id,
        slesh_category=slesh_category,
        product_id=product_id,
        supplier_product_id=supplier_product_id,
        ml_per_sale=ml_per_sale,
        bar_id=None,
    )
    session.add(rule)
    await session.flush()
    return rule


async def _cleanup(session, tenant_id: UUID) -> None:
    """event_category_ingredients.product_id is ondelete=RESTRICT, and
    delete_tenant_cascade's fixed table list predates this module — it
    would try to delete Product while a rule row still references it.
    Clear the event_storage rows first so the shared cascade can proceed.
    """
    await session.execute(delete(EventCategoryIngredient).where(EventCategoryIngredient.tenant_id == tenant_id))
    await session.execute(delete(EventStockBarAllocation).where(EventStockBarAllocation.tenant_id == tenant_id))
    await session.execute(delete(SupplierProduct).where(SupplierProduct.tenant_id == tenant_id))
    await delete_tenant_cascade(session, tenant_id)


async def _make_allocation(
    session, tenant_id: UUID, event_id: UUID, bar_id: UUID,
    supplier_product_id: UUID, *, qty_allocated: Decimal,
) -> EventStockBarAllocation:
    alloc = EventStockBarAllocation(
        tenant_id=tenant_id,
        event_id=event_id,
        bar_id=bar_id,
        supplier_product_id=supplier_product_id,
        qty_allocated=qty_allocated,
    )
    session.add(alloc)
    await session.flush()
    return alloc


# ─── Tests ───────────────────────────────────────────────────────────

async def test_cascade_works_despite_slesh_category_mismatch():
    """Reproduces the exact Jul-5 pre-fix condition: slesh_category
    ('SPRITZ ARANCIO') does NOT match the product name ('Sprtiz'). Before
    Day 3's cutover this would zero out consumed_ml because the tx query
    joined on product.name; after the cutover it joins on product_id and
    the mismatch no longer matters.
    """
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id)
            bar = await _make_bar(session, tenant.id, event.id)
            product = await _make_product(session, tenant.id, name="Sprtiz")
            sp = await _make_supplier_product(session, tenant.id)
            await _make_recipe_rule(
                session, tenant.id, event.id, product.id, sp.id,
                slesh_category="SPRITZ ARANCIO",  # INTENTIONAL mismatch
            )
            await _make_allocation(
                session, tenant.id, event.id, bar.id, sp.id,
                qty_allocated=Decimal("4"),
            )
            for _ in range(10):
                await make_stock_transaction(
                    session, tenant.id, event.id, bar.id, product.id,
                    qty=Decimal("1"), source=TransactionSource.SLESH_POS,
                )

            rows = await compute_bar_supplier_stock(session, tenant.id, event.id)

            assert len(rows) == 1
            row = rows[0]
            assert row.consumed_ml == 600.0
            assert row.remaining_ml == 3400.0
            assert row.dispatched_ml == 4000.0
        finally:
            await _cleanup(session, tenant.id)


# ─── Day 2.5 — backfill drink-over-supply preference ─────────────────

async def test_backfill_prefers_drink_over_supply_when_ambiguous():
    """Two active products share the name 'NEGRONI' — one product_type=
    'drink', one 'supply'. The backfill must pick the drink (the sellable
    item) instead of skipping the row as AMBIGUOUS, and record it under
    summary.preferred_drink rather than summary.ambiguous.
    """
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id)
            sp = await _make_supplier_product(session, tenant.id)
            drink = await _make_product(
                session, tenant.id, name="NEGRONI", product_type=ProductType.DRINK,
            )
            supply = await _make_product(
                session, tenant.id, name="NEGRONI", product_type=ProductType.SUPPLY,
            )
            rule = EventCategoryIngredient(
                tenant_id=tenant.id,
                event_id=event.id,
                slesh_category="NEGRONI",
                product_id=None,
                supplier_product_id=sp.id,
                ml_per_sale=Decimal("30"),
                bar_id=None,
            )
            session.add(rule)
            await session.flush()

            summary = BackfillSummary()
            await _backfill_tenant(session, tenant.id, dry_run=False, summary=summary)

            assert summary.preferred_drink == 1
            assert summary.ambiguous == []

            await session.refresh(rule)
            assert rule.product_id == drink.id
            assert rule.product_id != supply.id
        finally:
            await _cleanup(session, tenant.id)


async def test_backfill_stays_ambiguous_when_no_drink_variant():
    """Two active products share the name 'NEGRONI' but NEITHER is
    product_type='drink' (supply + ingredient, both non-drink types).

    Note: the literal Day 2.5 spec asked for two 'supply'-type NEGRONI
    rows, but products has a partial unique index on
    (tenant_id, name, product_type) WHERE is_archived=false — two active
    rows of the *same* type with the same name would violate that
    constraint outright. Using supply + ingredient instead exercises the
    identical code path (zero 'drink' candidates -> still ambiguous)
    without hitting an IntegrityError.
    """
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id)
            sp = await _make_supplier_product(session, tenant.id)
            await _make_product(
                session, tenant.id, name="NEGRONI", product_type=ProductType.SUPPLY,
            )
            await _make_product(
                session, tenant.id, name="NEGRONI", product_type=ProductType.INGREDIENT,
            )
            rule = EventCategoryIngredient(
                tenant_id=tenant.id,
                event_id=event.id,
                slesh_category="NEGRONI",
                product_id=None,
                supplier_product_id=sp.id,
                ml_per_sale=Decimal("30"),
                bar_id=None,
            )
            session.add(rule)
            await session.flush()

            summary = BackfillSummary()
            await _backfill_tenant(session, tenant.id, dry_run=False, summary=summary)

            assert summary.preferred_drink == 0
            assert len(summary.ambiguous) == 1

            await session.refresh(rule)
            assert rule.product_id is None
        finally:
            await _cleanup(session, tenant.id)


async def test_cascade_works_when_slesh_category_matches_name():
    """Happy path: slesh_category equals the product name (pre-Jul-5
    assumption). Same math should hold now that the join is on product_id.
    """
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id)
            bar = await _make_bar(session, tenant.id, event.id)
            product = await _make_product(session, tenant.id, name="Sprtiz")
            sp = await _make_supplier_product(session, tenant.id)
            await _make_recipe_rule(
                session, tenant.id, event.id, product.id, sp.id,
                slesh_category="Sprtiz",  # matches product name
            )
            await _make_allocation(
                session, tenant.id, event.id, bar.id, sp.id,
                qty_allocated=Decimal("4"),
            )
            for _ in range(10):
                await make_stock_transaction(
                    session, tenant.id, event.id, bar.id, product.id,
                    qty=Decimal("1"), source=TransactionSource.SLESH_POS,
                )

            rows = await compute_bar_supplier_stock(session, tenant.id, event.id)

            assert len(rows) == 1
            row = rows[0]
            assert row.consumed_ml == 600.0
            assert row.remaining_ml == 3400.0
            assert row.dispatched_ml == 4000.0
        finally:
            await _cleanup(session, tenant.id)
