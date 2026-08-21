"""Factory helpers for alerts test suite.

Each factory inserts one row into the live dev DB and returns the ORM
object with its .id populated.  Tests MUST delete every row they create
— use the cleanup pattern from test_reports_flow.py (try/finally or the
db_cleanup fixture below).

Import pattern in test files:
    from tests.fixtures.alerts.factories import (
        make_tenant, make_event, make_bar,
        make_product, make_bar_stock, make_recipe, make_recipe_item,
        make_stock_transaction,
    )
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Tenant
from app.modules.events.models import Event, EventOrder, EventStatus
from app.modules.bars.models import Bar
from app.modules.products.models import Product, ProductType, ProductCategory, ProductUnit
from app.modules.bar_stock.models import BarStock
from app.modules.recipes.models import Recipe, RecipeItem
from app.modules.recipes.template_models import RecipeTemplate  # noqa: F401 — prime mapper
from app.modules.stock_transactions.models import StockTransaction, TransactionSource


# ── low-level row factories ───────────────────────────────────────────────────

async def make_tenant(session: AsyncSession, *, name: str | None = None) -> Tenant:
    slug = uuid.uuid4().hex[:12]
    t = Tenant(name=name or f"test-tenant-{slug}", slug=slug)
    session.add(t)
    await session.flush()
    return t


# Reuse the single seeded venue — tests don't create/delete venues
_SUNDANCE_VENUE_ID = uuid.UUID("1af3846d-14b4-41be-9b14-c6e390f87a60")


async def make_event(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    status: EventStatus = EventStatus.LIVE,
) -> Event:
    e = Event(
        tenant_id=tenant_id,
        venue_id=_SUNDANCE_VENUE_ID,
        name=f"test-event-{uuid.uuid4().hex[:8]}",
        status=status,
        expected_guest_count=100,
        scheduled_at=datetime.now(timezone.utc),
        scheduled_end_at=datetime.now(timezone.utc).replace(hour=23),
        version=1,
    )
    session.add(e)
    await session.flush()
    return e


async def make_bar(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    *,
    bar_type: str = "drinks",
) -> Bar:
    b = Bar(
        tenant_id=tenant_id,
        event_id=event_id,
        name=f"test-bar-{uuid.uuid4().hex[:8]}",
        bar_type=bar_type,
        is_active=True,
    )
    session.add(b)
    await session.flush()
    return b


async def make_product(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    unit: ProductUnit = ProductUnit.BOTTLE,
    product_type: ProductType = ProductType.DRINK,
    category: ProductCategory | None = None,
    name: str | None = None,
) -> Product:
    p = Product(
        tenant_id=tenant_id,
        name=name or f"test-product-{uuid.uuid4().hex[:8]}",
        product_type=product_type,
        category=category if category is not None else ProductCategory.BASIC_COCKTAIL,
        unit=unit,
        default_price_cents=1000,
        is_archived=False,
    )
    session.add(p)
    await session.flush()
    return p


async def make_bar_stock(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    bar_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    allocated_qty: Decimal = Decimal("100"),
    current_qty: Decimal = Decimal("100"),
    returned_qty: Decimal = Decimal("0"),
) -> BarStock:
    bs = BarStock(
        tenant_id=tenant_id,
        event_id=event_id,
        bar_id=bar_id,
        product_id=product_id,
        allocated_qty=allocated_qty,
        current_qty=current_qty,
        returned_qty=returned_qty,
    )
    session.add(bs)
    await session.flush()
    return bs


async def make_recipe(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    drink_product_id: uuid.UUID,
    *,
    yield_qty: Decimal = Decimal("1"),
    yield_unit: ProductUnit = ProductUnit.GLASS,
) -> Recipe:
    r = Recipe(
        tenant_id=tenant_id,
        drink_product_id=drink_product_id,
        yield_qty=yield_qty,
        yield_unit=yield_unit,
        display_name=f"test-recipe-{uuid.uuid4().hex[:8]}",
    )
    session.add(r)
    await session.flush()
    return r


async def make_recipe_item(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    recipe_id: uuid.UUID,
    ingredient_product_id: uuid.UUID,
    *,
    qty: Decimal = Decimal("50"),
    unit: ProductUnit = ProductUnit.ML,
) -> RecipeItem:
    ri = RecipeItem(
        tenant_id=tenant_id,
        recipe_id=recipe_id,
        ingredient_product_id=ingredient_product_id,
        qty=qty,
        unit=unit,
    )
    session.add(ri)
    await session.flush()
    return ri


async def make_stock_transaction(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    bar_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    qty: Decimal = Decimal("1"),
    source: TransactionSource = TransactionSource.MANUAL_ADJUSTMENT,
    idempotency_key: str | None = None,
    parent_transaction_id: uuid.UUID | None = None,
    bar_stock_id: uuid.UUID | None = None,
) -> StockTransaction:
    st = StockTransaction(
        tenant_id=tenant_id,
        event_id=event_id,
        bar_id=bar_id,
        product_id=product_id,
        qty=qty,
        source=source,
        source_idempotency_key=idempotency_key or uuid.uuid4().hex,
        parent_transaction_id=parent_transaction_id,
        bar_stock_id=bar_stock_id,
    )
    session.add(st)
    await session.flush()
    return st


async def make_event_order(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    *,
    bar_id: uuid.UUID | None = None,
    fiscal_gross_cents: int = 1000,
    subtotal_cents: int | None = None,
    order_type: str = "experience",
    confirmed_line_count: int = 1,
    refunded_line_count: int = 0,
    created_at_slesh: datetime | None = None,
) -> EventOrder:
    """One Slesh order-summary row (the money-of-record the dashboard and
    reports sum). bar_id=None models an order from an unmapped POS shop;
    confirmed_line_count=0 models a fully-refunded order."""
    eo = EventOrder(
        tenant_id=tenant_id,
        event_id=event_id,
        slesh_order_id=uuid.uuid4().hex,
        bar_id=bar_id,
        order_type=order_type,
        subtotal_cents=subtotal_cents if subtotal_cents is not None else fiscal_gross_cents,
        fiscal_gross_cents=fiscal_gross_cents,
        cart_line_count=confirmed_line_count + refunded_line_count,
        confirmed_line_count=confirmed_line_count,
        refunded_line_count=refunded_line_count,
        created_at_slesh=created_at_slesh or datetime.now(timezone.utc),
    )
    session.add(eo)
    await session.flush()
    return eo


async def make_sale_with_children(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    bar_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    qty: Decimal = Decimal("1"),
    count: int = 1,
    age_minutes: int = 0,
) -> list[StockTransaction]:
    """Create a parent sale + child transactions (matching real POS flow).
    The burn-rate evaluator filters on bar_stock_id IS NOT NULL (i.e.
    transactions that actually decremented a bar_stock row). Real
    production tx always have bar_stock_id set; this helper mirrors
    that by looking up the existing bar_stock row for (event,bar,product)
    and stamping its id on both parent and child rows.

    age_minutes: backdates created_at by this many minutes — useful for
    demand-spike tests that need to populate different time windows.
    """
    from datetime import timedelta
    from sqlalchemy import update, select as sa_select
    backdate_ts = datetime.now(timezone.utc) - timedelta(minutes=age_minutes) if age_minutes else None

    # Look up the bar_stock row created by the test's make_bar_stock call.
    # Real production tx always have this set; mirroring that here.
    bs_row = (await session.execute(
        sa_select(BarStock.id).where(
            BarStock.tenant_id == tenant_id,
            BarStock.event_id  == event_id,
            BarStock.bar_id    == bar_id,
            BarStock.product_id == product_id,
        )
    )).scalar_one_or_none()

    results = []
    for _ in range(count):
        parent = await make_stock_transaction(
            session, tenant_id, event_id, bar_id, product_id,
            qty=qty, source=TransactionSource.MANUAL_ADJUSTMENT,
            bar_stock_id=bs_row,
        )
        child = await make_stock_transaction(
            session, tenant_id, event_id, bar_id, product_id,
            qty=qty, source=TransactionSource.MANUAL_ADJUSTMENT,
            parent_transaction_id=parent.id,
            bar_stock_id=bs_row,
        )
        if backdate_ts is not None:
            await session.execute(
                update(StockTransaction)
                .where(StockTransaction.id.in_([parent.id, child.id]))
                .values(created_at=backdate_ts)
            )
        results.append(child)
    return results


# ── cleanup helper ────────────────────────────────────────────────────────────

async def delete_tenant_cascade(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Delete all rows created under a test tenant, in safe FK order."""
    from app.modules.alerts.models import Alert
    from app.modules.event_products.models import EventProduct
    from app.modules.customer_analytics.models import CustomerPurchase, CustomerSession
    from app.modules.pos.models import IngestionLineError
    from app.modules.predictions.models import ModelArtifact
    from app.modules.reports.models import Report
    for model in [
        Alert,
        IngestionLineError,
        ModelArtifact,
        Report,
        CustomerPurchase,
        CustomerSession,
        EventOrder,
        StockTransaction,
        EventProduct,
        RecipeItem,
        Recipe,
        BarStock,
        Bar,
        Product,
        Event,
        Tenant,
    ]:
        await session.execute(
            delete(model).where(model.tenant_id == tenant_id)
            if hasattr(model, "tenant_id")
            else delete(model).where(model.id == tenant_id)
        )
    await session.commit()
