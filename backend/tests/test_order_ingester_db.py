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
    make_bar,
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
    operator: Any = None       # Phase 3: _User | str | None
    user: Any = None           # wristband holder, currently unused by tests
    created_at: int = 0        # ms since epoch, Slesh's format


@dataclass
class _User:
    """Mirrors the Pydantic User shape from app.modules.pos.schemas:
    a Slesh operator or wristband holder."""
    id: str | None = None      # Mongo _id (raw value, not aliased)
    type: str | None = None    # "operator" | "user"
    tag: str | None = None
    info: dict | None = None


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
# ─────────────────────────────────────────────────────────────────────
# Phase 3 (Jun 21 2026) — bar_device live-touch
# ─────────────────────────────────────────────────────────────────────
# These exercise _touch_bar_device directly with a real session.
# Each test covers one resolution branch:
#   1. match by Mongo _id (fast path, future steady-state)
#   2. match by email + backfill the Mongo _id (Excel-imported rows)
#   3. lazy-create on miss (defensive — Phase 4 wizard will pre-populate)
#   4. monotonic last_order_at (out-of-order polls must not rewind it)
from datetime import datetime, timedelta, timezone as _tz

from app.modules.bars.device_model import BarDevice
from app.modules.pos.order_ingester import _touch_bar_device


async def _make_bar_device(
    session, *,
    tenant_id, event_id, bar_id,
    slesh_operator_id: str,
    slesh_operator_email: str,
    is_active: bool = False,
    last_order_at: datetime | None = None,
) -> BarDevice:
    """Inline factory — no make_bar_device in fixtures/."""
    bd = BarDevice(
        tenant_id            = tenant_id,
        event_id             = event_id,
        bar_id               = bar_id,
        slesh_operator_id    = slesh_operator_id,
        slesh_operator_email = slesh_operator_email,
        device_number        = None,
        role                 = "bartender",
        display_name         = None,
        is_active            = is_active,
        last_order_at        = last_order_at,
    )
    session.add(bd)
    await session.flush()
    return bd


async def test_touch_bar_device_matches_by_mongo_id():
    """Existing row keyed by Mongo _id — fast-path lookup, flipped active."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event  = await make_event(session, tenant.id)
        bar    = await make_bar(session, tenant.id, event.id)

        bd = await _make_bar_device(
            session,
            tenant_id            = tenant.id,
            event_id             = event.id,
            bar_id               = bar.id,
            slesh_operator_id    = "6650abc1234def5678e2f9aa",
            slesh_operator_email = "Ss-bar-main-3@slesh.it",
            is_active            = False,
            last_order_at        = None,
        )

        operator = _User(
            id   = "6650abc1234def5678e2f9aa",
            type = "operator",
            info = {"email": "Ss-bar-main-3@slesh.it", "name": "Mario"},
        )
        ts = datetime(2026, 7, 5, 22, 30, tzinfo=_tz.utc)

        await _touch_bar_device(
            db=session, tenant_id=tenant.id, event_id=event.id,
            bar_id=bar.id, operator=operator, order_created_at=ts,
        )
        await session.flush()
        await session.refresh(bd)

        assert bd.is_active is True
        assert bd.last_order_at == ts

        # No duplicate row created
        total = await session.scalar(
            select(func.count()).select_from(BarDevice)
            .where(BarDevice.event_id == event.id)
        )
        assert total == 1

        await delete_tenant_cascade(session, tenant.id)


async def test_touch_bar_device_matches_by_email_and_backfills_mongo_id():
    """Excel-imported row stores email as slesh_operator_id. When a live
    order arrives with the real Mongo _id, we should match via email
    AND overwrite slesh_operator_id with the real _id."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event  = await make_event(session, tenant.id)
        bar    = await make_bar(session, tenant.id, event.id)

        # Excel-style row: slesh_operator_id is the email (placeholder)
        bd = await _make_bar_device(
            session,
            tenant_id            = tenant.id,
            event_id             = event.id,
            bar_id               = bar.id,
            slesh_operator_id    = "Ss-bar-stage-2@slesh.it",
            slesh_operator_email = "Ss-bar-stage-2@slesh.it",
            is_active            = False,
        )

        operator = _User(
            id   = "6650bbb1234def5678e2f9bb",   # real Mongo _id
            type = "operator",
            info = {"email": "Ss-bar-stage-2@slesh.it"},
        )
        ts = datetime(2026, 7, 5, 23, 0, tzinfo=_tz.utc)

        await _touch_bar_device(
            db=session, tenant_id=tenant.id, event_id=event.id,
            bar_id=bar.id, operator=operator, order_created_at=ts,
        )
        await session.flush()
        await session.refresh(bd)

        assert bd.is_active is True
        assert bd.last_order_at == ts
        assert bd.slesh_operator_id == "6650bbb1234def5678e2f9bb"
        # Email column untouched — that's the stable, human-readable label
        assert bd.slesh_operator_email == "Ss-bar-stage-2@slesh.it"

        total = await session.scalar(
            select(func.count()).select_from(BarDevice)
            .where(BarDevice.event_id == event.id)
        )
        assert total == 1

        await delete_tenant_cascade(session, tenant.id)


async def test_touch_bar_device_lazy_creates_when_missing():
    """No matching row anywhere -> create a new active device row.
    Defensive: Phase 4 wizard pre-populates, but unmapped operators
    can surface mid-event (new staff, ad-hoc devices) and must be tracked."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event  = await make_event(session, tenant.id)
        bar    = await make_bar(session, tenant.id, event.id)

        # NO pre-existing bar_devices row.
        operator = _User(
            id   = "6650ccc1234def5678e2f9cc",
            type = "operator",
            info = {"email": "Ss-bar-three-1@slesh.it", "name": "Sara"},
        )
        ts = datetime(2026, 7, 5, 21, 0, tzinfo=_tz.utc)

        await _touch_bar_device(
            db=session, tenant_id=tenant.id, event_id=event.id,
            bar_id=bar.id, operator=operator, order_created_at=ts,
        )
        await session.flush()

        created = await session.scalar(
            select(BarDevice)
            .where(BarDevice.event_id == event.id)
            .where(BarDevice.slesh_operator_id == "6650ccc1234def5678e2f9cc")
        )
        assert created is not None
        assert created.is_active is True
        assert created.last_order_at == ts
        assert created.slesh_operator_email == "Ss-bar-three-1@slesh.it"
        assert created.role == "bartender"
        assert created.bar_id == bar.id

        await delete_tenant_cascade(session, tenant.id)


async def test_touch_bar_device_last_order_at_is_monotonic():
    """An older order arriving after a newer one (rare but possible with
    polling overlap) must not rewind last_order_at."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event  = await make_event(session, tenant.id)
        bar    = await make_bar(session, tenant.id, event.id)

        newer = datetime(2026, 7, 5, 23, 30, tzinfo=_tz.utc)
        older = newer - timedelta(minutes=15)

        bd = await _make_bar_device(
            session,
            tenant_id            = tenant.id,
            event_id             = event.id,
            bar_id               = bar.id,
            slesh_operator_id    = "6650ddd1234def5678e2f9dd",
            slesh_operator_email = "Ss-bar-main-1@slesh.it",
            is_active            = True,
            last_order_at        = newer,
        )

        operator = _User(
            id   = "6650ddd1234def5678e2f9dd",
            type = "operator",
            info = {"email": "Ss-bar-main-1@slesh.it"},
        )

        # Older order arrives — must not regress last_order_at
        await _touch_bar_device(
            db=session, tenant_id=tenant.id, event_id=event.id,
            bar_id=bar.id, operator=operator, order_created_at=older,
        )
        await session.flush()
        await session.refresh(bd)

        assert bd.last_order_at == newer  # held its ground
        assert bd.is_active is True       # still active

        await delete_tenant_cascade(session, tenant.id)
# ─────────────────────────────────────────────────────────────────────
# Phase 4 step 4 (Jun 21 2026) — bar-type auto-classification
# ─────────────────────────────────────────────────────────────────────
# Plan-B safety net: if Omar forgets to configure a food vendor in the
# Create Event wizard, the ingester auto-creates a stub bar with
# bar_type='drinks' (the default). Without reclassification, the food
# truck renders as a drinks card with €0 stock — wrong. With it, the
# stub flips to bar_type='food' as soon as the first food-only signal
# arrives, and the FoodBarCard renders correctly.
from app.modules.bars.models import Bar


async def test_auto_created_bar_with_only_food_products_reclassifies_to_food():
    """Auto-created stub selling exclusively food products should flip
    bar_type='drinks' -> 'food' so the dashboard renders FoodBarCard."""
    SHOP_ID = "6650food1234def5678e2faa"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup(session, external_pos_id="ext-burger")
        prod.product_type = ProductType.FOOD
        await session.flush()

        order = _Order(
            id="o-food-1",
            cart=[_CartLine(id="l-1", product="ext-burger", gross_amount=1200)],
            shop=_Shop(id=SHOP_ID, name="MALANDRINO Slesh"),
            payment=_Payment(type="cash"),
        )
        svc = StockTransactionService(session)
        await ingest_order(
            db=session, order=order, event_id=ev.id,
            tenant_id=tenant.id, service=svc,
        )
        await session.flush()

        # Bar should exist + be reclassified
        bar = await session.scalar(
            select(Bar).where(Bar.event_id == ev.id).where(Bar.slesh_negozio_id == SHOP_ID)
        )
        assert bar is not None
        assert bar.auto_created is True
        assert bar.bar_type == "food", (
            f"expected bar_type='food', got {bar.bar_type!r} — "
            f"the food-only auto-classifier did not fire"
        )

        await delete_tenant_cascade(session, tenant.id)


async def test_auto_created_bar_with_mixed_products_stays_drinks():
    """Auto-created stub selling at least one DRINK alongside food
    must NOT flip to bar_type='food'. Mixed bars stay as drinks
    (BarCard renders fine for mixed; FoodBarCard would mislead)."""
    SHOP_ID = "6650mixed1234def5678e2bb"
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        ev = await make_event(session, tenant.id)

        drink_prod = await make_product(session, tenant.id, product_type=ProductType.DRINK)
        drink_prod.external_pos_id = "ext-heineken"
        drink_prod.default_price_cents = 700

        food_prod = await make_product(session, tenant.id, product_type=ProductType.FOOD)
        food_prod.external_pos_id = "ext-burger"
        food_prod.default_price_cents = 1200
        await session.flush()

        svc = StockTransactionService(session)

        # First order: one DRINK at the bar
        await ingest_order(
            db=session,
            order=_Order(
                id="o-mixed-1",
                cart=[_CartLine(id="l-1", product="ext-heineken", gross_amount=700)],
                shop=_Shop(id=SHOP_ID, name="MIXED BAR"),
                payment=_Payment(type="cash"),
            ),
            event_id=ev.id, tenant_id=tenant.id, service=svc,
        )
        await session.flush()

        # Second order: a FOOD product at the SAME bar — must NOT flip
        # since prior DRINK transaction disqualifies it.
        await ingest_order(
            db=session,
            order=_Order(
                id="o-mixed-2",
                cart=[_CartLine(id="l-2", product="ext-burger", gross_amount=1200)],
                shop=_Shop(id=SHOP_ID, name="MIXED BAR"),
                payment=_Payment(type="cash"),
            ),
            event_id=ev.id, tenant_id=tenant.id, service=svc,
        )
        await session.flush()

        bar = await session.scalar(
            select(Bar).where(Bar.event_id == ev.id).where(Bar.slesh_negozio_id == SHOP_ID)
        )
        assert bar is not None
        assert bar.auto_created is True
        assert bar.bar_type == "drinks", (
            f"expected bar_type='drinks' (mixed sales seen), got {bar.bar_type!r}"
        )

        await delete_tenant_cascade(session, tenant.id)
