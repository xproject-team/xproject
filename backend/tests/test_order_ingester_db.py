"""Real-PG tests for the no-data-loss invariant in order ingestion.

Fake tests in test_order_ingester.py prove routing logic against
monkey-patched lookups; this file proves the auto-create branch in
_resolve_bar actually persists a Bar row to Postgres, the order lands
as a StockTransaction attributed to that bar, and a second order from
the same shop_id reuses the bar without creating a duplicate. This is
the Phase 2a invariant in concrete terms: every Slesh sale lands
somewhere, even for unmapped shops.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import func, select

from app.modules.bars.models import Bar
from app.modules.pos.order_ingester import ingest_order
from app.modules.products.models import ProductType
from app.modules.stock_transactions.models import StockTransaction
from app.modules.stock_transactions.service import StockTransactionService
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_event,
    make_product,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


@dataclass
class _Shop:
    id: str
    name: str | None = None


@dataclass
class _Payment:
    type: str | None
    status: str | None = None


@dataclass
class _CartLine:
    id: str
    product: str            # Product.external_pos_id
    gross_amount: int = 1500
    status: str | None = "completed"
    product_name: Any = None


@dataclass
class _Order:
    id: str
    cart: list[_CartLine]
    shop: _Shop
    payment: _Payment | None = None
    type: str = "experience"
    status: str = "completed"


async def _setup(session, *, external_pos_id: str):
    tenant = await make_tenant(session)
    ev = await make_event(session, tenant.id)
    prod = await make_product(session, tenant.id, product_type=ProductType.DRINK)
    prod.external_pos_id = external_pos_id
    prod.default_price_cents = 1500
    await session.flush()
    return tenant, ev, prod


async def test_unmapped_shop_auto_creates_bar_and_lands_sale():
    """First order for unmapped shop -> bar auto-created with
    auto_created=True, truncated shop_id as name; sale lands."""
    SHOP_ID = "6650abc1234def5678e2f9aa"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup(session, external_pos_id="prod_A")
        try:
            svc = StockTransactionService(session)
            order = _Order(
                id="ord_1",
                shop=_Shop(id=SHOP_ID, name="Some New Shop"),
                cart=[_CartLine(id="line_1", product="prod_A", gross_amount=1500)],
                payment=_Payment(type="card"),
            )
            result = await ingest_order(
                db=session, order=order, event_id=ev.id, tenant_id=tenant.id,
                service=svc,
            )
            await session.flush()

            assert result.lines_skipped == 0
            assert result.lines_ingested == 1
            assert result.lines_errors == 0

            bars = (await session.execute(
                select(Bar).where(Bar.tenant_id == tenant.id, Bar.event_id == ev.id)
            )).scalars().all()
            assert len(bars) == 1
            bar = bars[0]
            assert bar.slesh_negozio_id == SHOP_ID
            assert bar.auto_created is True
            assert bar.name == f"{SHOP_ID[:8]}\u2026{SHOP_ID[-4:]}"
            assert bar.bar_type == "drinks"
            assert bar.is_active is True

            tx_count = await session.scalar(
                select(func.count()).select_from(StockTransaction).where(
                    StockTransaction.tenant_id == tenant.id,
                    StockTransaction.event_id == ev.id,
                    StockTransaction.bar_id == bar.id,
                )
            )
            assert tx_count == 1
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_unmapped_shop_reused_on_second_order():
    """Second order from same unmapped shop_id reuses the auto-created
    bar; no duplicate. Two transactions land on the same bar."""
    SHOP_ID = "shop1234567890abcdef1234"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup(session, external_pos_id="prod_B")
        try:
            svc = StockTransactionService(session)
            for order_id, line_id in [("ord_A", "lineA"), ("ord_B", "lineB")]:
                order = _Order(
                    id=order_id,
                    shop=_Shop(id=SHOP_ID),
                    cart=[_CartLine(id=line_id, product="prod_B", gross_amount=1500)],
                    payment=_Payment(type="card"),
                )
                result = await ingest_order(
                    db=session, order=order, event_id=ev.id, tenant_id=tenant.id,
                    service=svc,
                )
                await session.flush()
                assert result.lines_ingested == 1, f"order {order_id} should ingest"

            bar_count = await session.scalar(
                select(func.count()).select_from(Bar).where(
                    Bar.tenant_id == tenant.id, Bar.event_id == ev.id,
                )
            )
            assert bar_count == 1, "auto-created bar must be reused, not duplicated"

            tx_count = await session.scalar(
                select(func.count()).select_from(StockTransaction).where(
                    StockTransaction.tenant_id == tenant.id,
                    StockTransaction.event_id == ev.id,
                )
            )
            assert tx_count == 2
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()
