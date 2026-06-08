"""Service-level DB tests for StockTransactionService.ingest_food_sale.

The Slesh order ingester routes FOOD cart lines to ingest_food_sale (added
in the food-revenue fix). The drink/recipe path (ingest_sale) is exercised
only through faked tests; this is the first real-Postgres test of the food
path, which is the revenue path for food trucks at Sundance.

Proves, with TestSessionLocal + delete_tenant_cascade cleanup:
  - a FOOD slesh_pos sale lands as ONE priced parent row, no recipe children
  - the food's bar_stock current_qty is decremented by the sold qty
  - re-ingesting the same Slesh line (same idempotency key) is a no-op replay
  - handing a DRINK to ingest_food_sale raises NotAFoodError

Same fixture style as test_event_kpi_summary.py.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.products.models import FoodType, ProductType
from app.modules.stock_transactions.models import (
    PaymentType,
    StockTransaction,
    TransactionSource,
)
from app.modules.stock_transactions.schemas import SaleIngestRequest
from app.modules.stock_transactions.service import (
    NotAFoodError,
    StockTransactionService,
)
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_bar,
    make_bar_stock,
    make_event,
    make_product,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def _make_food(session, tenant_id):
    """Food product mirroring the KPI test helper (null category + food_type)."""
    p = await make_product(session, tenant_id, product_type=ProductType.FOOD)
    p.category = None
    p.food_type = FoodType.BURGERS
    await session.flush()
    return p


def _food_req(*, event_id, bar_id, product_id, key, qty="1", price_cents=1500):
    return SaleIngestRequest(
        event_id=event_id,
        bar_id=bar_id,
        product_id=product_id,
        qty=Decimal(qty),
        price_cents=price_cents,
        source=TransactionSource.SLESH_POS,
        source_idempotency_key=key,
        payment_type=PaymentType.CARD,
    )


async def test_food_sale_lands_one_priced_parent_no_children():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            bar = await make_bar(session, tenant.id, ev.id)
            food = await _make_food(session, tenant.id)
            await make_bar_stock(
                session, tenant.id, ev.id, bar.id, food.id, current_qty=Decimal("10"),
            )

            svc = StockTransactionService(session)
            req = _food_req(
                event_id=ev.id, bar_id=bar.id, product_id=food.id,
                key="slesh:ordF:lineF", qty="1", price_cents=1500,
            )
            res = await svc.ingest_food_sale(tenant.id, req)
            await session.flush()

            assert res.idempotency_replay is False
            assert res.children == []
            p = res.parent
            assert p.source is TransactionSource.SLESH_POS
            assert p.price_cents == 1500
            assert p.qty == Decimal("1")
            assert p.parent_transaction_id is None
            assert p.product_id == food.id
            assert p.bar_id == bar.id
            assert p.event_id == ev.id
            assert p.deficit_qty == Decimal("0")
            assert p.payment_type == PaymentType.CARD

            n = await session.scalar(
                select(func.count()).select_from(StockTransaction).where(
                    StockTransaction.tenant_id == tenant.id,
                    StockTransaction.source_idempotency_key == "slesh:ordF:lineF",
                )
            )
            assert n == 1
            kids = await session.scalar(
                select(func.count()).select_from(StockTransaction).where(
                    StockTransaction.parent_transaction_id == p.id,
                )
            )
            assert kids == 0
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_food_sale_decrements_bar_stock():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            bar = await make_bar(session, tenant.id, ev.id)
            food = await _make_food(session, tenant.id)
            bs = await make_bar_stock(
                session, tenant.id, ev.id, bar.id, food.id, current_qty=Decimal("10"),
            )

            svc = StockTransactionService(session)
            req = _food_req(
                event_id=ev.id, bar_id=bar.id, product_id=food.id,
                key="slesh:ordF:lineDec", qty="3", price_cents=1500,
            )
            res = await svc.ingest_food_sale(tenant.id, req)
            await session.flush()

            assert bs.current_qty == Decimal("7")   # 10 - 3
            assert res.parent.bar_stock_id == bs.id
            assert res.parent.deficit_qty == Decimal("0")
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_food_sale_replay_is_idempotent():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            bar = await make_bar(session, tenant.id, ev.id)
            food = await _make_food(session, tenant.id)
            await make_bar_stock(
                session, tenant.id, ev.id, bar.id, food.id, current_qty=Decimal("10"),
            )

            svc = StockTransactionService(session)
            key = "slesh:ordF:lineReplay"
            first = await svc.ingest_food_sale(
                tenant.id,
                _food_req(event_id=ev.id, bar_id=bar.id, product_id=food.id, key=key),
            )
            await session.flush()
            second = await svc.ingest_food_sale(
                tenant.id,
                _food_req(event_id=ev.id, bar_id=bar.id, product_id=food.id, key=key),
            )
            await session.flush()

            assert first.idempotency_replay is False
            assert second.idempotency_replay is True
            assert second.parent.id == first.parent.id

            n = await session.scalar(
                select(func.count()).select_from(StockTransaction).where(
                    StockTransaction.tenant_id == tenant.id,
                    StockTransaction.source_idempotency_key == key,
                )
            )
            assert n == 1
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_ingest_food_sale_rejects_drink():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            bar = await make_bar(session, tenant.id, ev.id)
            drink = await make_product(session, tenant.id, product_type=ProductType.DRINK)

            svc = StockTransactionService(session)
            req = _food_req(
                event_id=ev.id, bar_id=bar.id, product_id=drink.id,
                key="slesh:ordF:lineDrink",
            )
            with pytest.raises(NotAFoodError) as exc:
                await svc.ingest_food_sale(tenant.id, req)
            assert exc.value.actual_type == "drink"
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()
