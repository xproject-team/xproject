"""Tests for the phantom-bar defensive fix (Jul-19 sprint).

Root cause of the Sundance Jul-5 incidents: three food trucks came
online mid-event with no bar.slesh_negozio_id set. The first order
from each unmapped shop_id caused order_ingester._resolve_bar to
silently auto-create a phantom bar (see order_ingester.py). Omar had
to manually SQL-merge phantoms into the real bars three times during
the event.

These tests prove the fix end-to-end against a real Postgres session:
unmapped shop_ids now park in pending_shop_mappings and fire a WARNING
alert instead of creating a bar (tests 1-3), and the operator-facing
resolve path links a bar + replays every parked order (tests 4-5).

Uses real app.modules.pos.schemas.Order/CartLine/ShopRef/Payment
instances (not the lightweight dataclass fakes in
test_order_ingester_db.py) — park_unmapped_order() round-trips orders
through Order.model_dump()/model_validate() for replay, which requires
genuine pydantic instances.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.modules.alerts.models import Alert
from app.modules.bars.models import Bar
from app.modules.pos.models import PendingShopMapping
from app.modules.pos.order_ingester import ingest_order
from app.modules.pos.pending_shop_mappings_service import (
    PendingMappingAlreadyResolvedError,
    resolve,
)
from app.modules.pos.schemas import CartLine, Order, Payment, ShopRef
from app.modules.products.models import ProductType
from app.modules.stock_transactions.models import StockTransaction
from app.modules.stock_transactions.service import StockTransactionService
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_bar,
    make_event,
    make_product,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


# ─── Helpers ─────────────────────────────────────────────────────────

def _make_order(
    *, order_id: str, shop_id: str, line_id: str, product_ext_id: str,
    gross_amount: int = 1500,
) -> Order:
    return Order(
        id=order_id,
        type="experience",
        created_at=1700000000000,
        shop=ShopRef(id=shop_id, name="Some New Shop"),
        cart=[CartLine(id=line_id, product=product_ext_id, gross_amount=gross_amount)],
        payment=Payment(type="card"),
    )


async def _setup_tenant_event_product(session, *, external_pos_id: str):
    tenant = await make_tenant(session)
    ev = await make_event(session, tenant.id)
    prod = await make_product(session, tenant.id, product_type=ProductType.DRINK)
    prod.external_pos_id = external_pos_id
    prod.default_price_cents = 1500
    await session.flush()
    return tenant, ev, prod


# ─── Tests ───────────────────────────────────────────────────────────

async def test_ingester_creates_pending_mapping_on_unknown_shop():
    """First order for an unmapped shop_id must NOT auto-create a bar;
    it must park in pending_shop_mappings instead."""
    SHOP_ID = "6650phantom1234def5678aa"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup_tenant_event_product(session, external_pos_id="prod_A")
        try:
            svc = StockTransactionService(session)
            order = _make_order(
                order_id="ord_1", shop_id=SHOP_ID, line_id="line_1",
                product_ext_id="prod_A", gross_amount=1500,
            )
            result = await ingest_order(
                db=session, order=order, event_id=ev.id, tenant_id=tenant.id,
                service=svc,
            )
            await session.flush()

            # No bar created for this shop_id
            bars = (await session.execute(
                select(Bar).where(Bar.tenant_id == tenant.id, Bar.event_id == ev.id)
            )).scalars().all()
            assert bars == [], "unmapped shop_id must not auto-create a bar"

            # Order was parked, not ingested
            assert result.lines_ingested == 0
            assert result.lines_skipped == result.lines_total

            pending = (await session.execute(
                select(PendingShopMapping).where(
                    PendingShopMapping.tenant_id == tenant.id,
                    PendingShopMapping.slesh_shop_id == SHOP_ID,
                )
            )).scalar_one()
            assert pending.event_id == ev.id
            assert pending.order_count == 1
            assert pending.total_gross_cents == 1500
            assert pending.resolved_at is None
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_ingester_fires_alert_on_unknown_shop():
    """Parking an order for an unmapped shop_id must fire a WARNING
    alert (alert_type='system', context_json.category='unmapped_shop')
    with no bar attached."""
    SHOP_ID = "6650alert1234def5678bbcc"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup_tenant_event_product(session, external_pos_id="prod_B")
        try:
            svc = StockTransactionService(session)
            order = _make_order(
                order_id="ord_2", shop_id=SHOP_ID, line_id="line_2",
                product_ext_id="prod_B", gross_amount=2000,
            )
            await ingest_order(
                db=session, order=order, event_id=ev.id, tenant_id=tenant.id,
                service=svc,
            )
            await session.flush()

            alert = (await session.execute(
                select(Alert).where(
                    Alert.tenant_id == tenant.id,
                    Alert.event_id == ev.id,
                    Alert.alert_type == "system",
                )
            )).scalar_one()
            assert alert.bar_id is None
            assert alert.severity == "warning"
            assert alert.audience == "owner_only"
            assert alert.context_json["category"] == "unmapped_shop"
            assert alert.context_json["slesh_shop_id"] == SHOP_ID
            assert "1 orders" in alert.owner_message or "1" in alert.owner_message
            assert SHOP_ID in alert.owner_message
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_ingester_increments_pending_row_on_second_unknown_order():
    """Two different orders from the SAME unmapped shop_id must
    accumulate onto ONE pending_shop_mappings row, not create two."""
    SHOP_ID = "6650twice1234def5678ddee"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup_tenant_event_product(session, external_pos_id="prod_C")
        try:
            svc = StockTransactionService(session)
            for order_id, line_id, amount in [("ord_a", "line_a", 1000), ("ord_b", "line_b", 1200)]:
                order = _make_order(
                    order_id=order_id, shop_id=SHOP_ID, line_id=line_id,
                    product_ext_id="prod_C", gross_amount=amount,
                )
                await ingest_order(
                    db=session, order=order, event_id=ev.id, tenant_id=tenant.id,
                    service=svc,
                )
                await session.flush()

            rows = (await session.execute(
                select(PendingShopMapping).where(
                    PendingShopMapping.tenant_id == tenant.id,
                    PendingShopMapping.slesh_shop_id == SHOP_ID,
                )
            )).scalars().all()
            assert len(rows) == 1, "must accumulate onto one row, not create a second"
            pending = rows[0]
            assert pending.order_count == 2
            assert pending.total_gross_cents == 1000 + 1200
            assert len(pending.parked_orders_json) == 2
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_resolve_endpoint_updates_bar_and_replays():
    """Resolving a pending mapping must set the bar's slesh_negozio_id,
    mark the row resolved, and replay every parked order as a real
    StockTransaction against that bar."""
    SHOP_ID = "6650resolve1234def5678ff"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup_tenant_event_product(session, external_pos_id="prod_D")
        try:
            bar = await make_bar(session, tenant.id, ev.id)
            assert bar.slesh_negozio_id is None

            svc = StockTransactionService(session)
            for i in range(3):
                order = _make_order(
                    order_id=f"ord_resolve_{i}", shop_id=SHOP_ID,
                    line_id=f"line_resolve_{i}", product_ext_id="prod_D",
                    gross_amount=1500,
                )
                await ingest_order(
                    db=session, order=order, event_id=ev.id, tenant_id=tenant.id,
                    service=svc,
                )
                await session.flush()

            pending = (await session.execute(
                select(PendingShopMapping).where(
                    PendingShopMapping.tenant_id == tenant.id,
                    PendingShopMapping.slesh_shop_id == SHOP_ID,
                )
            )).scalar_one()
            assert pending.order_count == 3

            summary = await resolve(
                session, tenant_id=tenant.id, event_id=ev.id,
                pending_id=pending.id, bar_id=bar.id,
            )
            assert summary["orders_replayed"] == 3
            assert summary["lines_replayed"] == 3

            await session.refresh(bar)
            assert bar.slesh_negozio_id == SHOP_ID

            await session.refresh(pending)
            assert pending.resolved_at is not None
            assert pending.resolved_bar_id == bar.id

            tx_count = await session.scalar(
                select(StockTransaction.id).where(
                    StockTransaction.tenant_id == tenant.id,
                    StockTransaction.bar_id == bar.id,
                ).limit(100)
            )
            tx_rows = (await session.execute(
                select(StockTransaction).where(
                    StockTransaction.tenant_id == tenant.id,
                    StockTransaction.bar_id == bar.id,
                )
            )).scalars().all()
            assert len(tx_rows) == 3

            # The alert fired while pending must auto-resolve on resolution.
            alert = (await session.execute(
                select(Alert).where(
                    Alert.tenant_id == tenant.id,
                    Alert.event_id == ev.id,
                    Alert.alert_type == "system",
                )
            )).scalar_one()
            assert alert.auto_resolved_at is not None
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_resolve_endpoint_idempotent():
    """Resolving the same pending mapping twice must not double-replay
    orders — the second call raises rather than silently repeating."""
    SHOP_ID = "6650idem1234def5678aabb"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup_tenant_event_product(session, external_pos_id="prod_E")
        try:
            bar = await make_bar(session, tenant.id, ev.id)
            svc = StockTransactionService(session)
            order = _make_order(
                order_id="ord_idem", shop_id=SHOP_ID, line_id="line_idem",
                product_ext_id="prod_E", gross_amount=1500,
            )
            await ingest_order(
                db=session, order=order, event_id=ev.id, tenant_id=tenant.id,
                service=svc,
            )
            await session.flush()

            pending = (await session.execute(
                select(PendingShopMapping).where(
                    PendingShopMapping.tenant_id == tenant.id,
                    PendingShopMapping.slesh_shop_id == SHOP_ID,
                )
            )).scalar_one()

            first = await resolve(
                session, tenant_id=tenant.id, event_id=ev.id,
                pending_id=pending.id, bar_id=bar.id,
            )
            assert first["orders_replayed"] == 1

            with pytest.raises(PendingMappingAlreadyResolvedError):
                await resolve(
                    session, tenant_id=tenant.id, event_id=ev.id,
                    pending_id=pending.id, bar_id=bar.id,
                )

            # No duplicate replay — still exactly 1 transaction.
            tx_rows = (await session.execute(
                select(StockTransaction).where(
                    StockTransaction.tenant_id == tenant.id,
                    StockTransaction.bar_id == bar.id,
                )
            )).scalars().all()
            assert len(tx_rows) == 1
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()
