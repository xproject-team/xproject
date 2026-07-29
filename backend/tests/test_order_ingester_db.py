"""Real-PG tests for the no-data-loss invariant in order ingestion.

Fake tests in test_order_ingester.py prove routing logic against
monkey-patched lookups; this file proves real-Postgres behavior for
bar resolution and the bar-type auto-classifier.

Jul-19 sprint: _resolve_bar no longer auto-creates a phantom bar for an
unmapped shop_id (that's the fix — see order_ingester.py + Sundance
Jul-5 incident notes). The two tests that used to assert the OLD
auto-create-and-land behavior (test_unmapped_shop_auto_creates_bar_and_lands_sale,
test_unmapped_shop_reused_on_second_order) have been superseded by
tests/test_pending_shop_mappings.py, which asserts the NEW behavior:
no bar created, the order is parked, and an alert fires instead.

The two bar-type auto-classification tests below still apply — that
logic (_maybe_classify_bar_as_food) only ever ran on already-existing
auto_created=True bars, regardless of how they came to exist. Their
setup now constructs that bar directly (mirroring what the OLD
auto-create used to produce) instead of relying on the ingester to
create it via an unmapped shop_id, since the ingester no longer does
that.
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
    payment_token: str | None = None  # physical wristband/card credential


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
    customer_email: str | None = None
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


# test_unmapped_shop_auto_creates_bar_and_lands_sale and
# test_unmapped_shop_reused_on_second_order were removed here (Jul-19
# sprint) -- they asserted the OLD phantom-bar auto-create behavior,
# which this sprint's fix removes. See tests/test_pending_shop_mappings.py
# for the tests covering the NEW behavior (park + alert, no bar created).
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
# Plan-B safety net: an auto_created=True stub bar defaults to
# bar_type='drinks'. Without reclassification, a food truck renders as
# a drinks card with €0 stock — wrong. With it, the stub flips to
# bar_type='food' as soon as the first food-only signal arrives, and
# the FoodBarCard renders correctly.
#
# Jul-19 sprint: the ingester no longer auto-creates this stub itself
# (see order_ingester.py — that's the phantom-bar fix). The classifier
# logic (_maybe_classify_bar_as_food) is unchanged and still only ever
# applies to bar.auto_created=True bars, regardless of how they came to
# exist — these tests now construct that bar directly (mirroring what
# the OLD auto-create used to produce) instead of relying on an
# unmapped shop_id to trigger creation via the ingester.
from app.modules.bars.models import Bar


async def _make_auto_created_bar(session, tenant_id, event_id, *, shop_id: str, name: str) -> Bar:
    bar = Bar(
        tenant_id=tenant_id,
        event_id=event_id,
        name=name,
        slesh_negozio_id=shop_id,
        bar_type="drinks",
        is_active=True,
        auto_created=True,
    )
    session.add(bar)
    await session.flush()
    return bar


async def test_auto_created_bar_with_only_food_products_reclassifies_to_food():
    """Auto-created stub selling exclusively food products should flip
    bar_type='drinks' -> 'food' so the dashboard renders FoodBarCard."""
    SHOP_ID = "6650food1234def5678e2faa"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup(session, external_pos_id="ext-burger")
        prod.product_type = ProductType.FOOD
        await _make_auto_created_bar(session, tenant.id, ev.id, shop_id=SHOP_ID, name="MALANDRINO Slesh")
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

        # Bar should be reclassified
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
        await _make_auto_created_bar(session, tenant.id, ev.id, shop_id=SHOP_ID, name="MIXED BAR")

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


# ─────────────────────────────────────────────────────────────────────
# customer_email / payment_token columns (Aug-2 identity task)
# ─────────────────────────────────────────────────────────────────────
from app.modules.events.models import EventOrder


async def _make_bar_with_shop(session, tenant_id, event_id, *, shop_id: str) -> Bar:
    bar = await make_bar(session, tenant_id, event_id)
    bar.slesh_negozio_id = shop_id
    await session.flush()
    return bar


async def test_ingest_order_persists_customer_email_and_payment_token():
    """Both new columns are populated from the order/payment payload,
    independently of raw_extras.user (the pre-existing Mongo id)."""
    SHOP_ID = "6650email1234def5678e2cc"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup(session, external_pos_id="ext-drink-1")
        bar = await _make_bar_with_shop(session, tenant.id, ev.id, shop_id=SHOP_ID)

        order = _Order(
            id="o-email-1",
            cart=[_CartLine(id="l-1", product="ext-drink-1")],
            shop=_Shop(id=SHOP_ID),
            payment=_Payment(type="token", payment_token="wristband-token-abc"),
            user="6650user1234def5678e2cc",
            customer_email="Jane.Doe@Example.com",
        )
        svc = StockTransactionService(session)
        await ingest_order(
            db=session, order=order, event_id=ev.id, tenant_id=tenant.id, service=svc,
        )
        await session.flush()

        row = await session.scalar(
            select(EventOrder).where(EventOrder.slesh_order_id == "o-email-1")
        )
        assert row is not None
        assert row.customer_email == "jane.doe@example.com"  # lowercased + trimmed
        assert row.payment_token == "wristband-token-abc"
        assert row.raw_extras["user"] == {"_id": "6650user1234def5678e2cc"}

        await delete_tenant_cascade(session, tenant.id)


async def test_ingest_order_customer_email_null_for_guest_orders():
    """Cash guest, never registered: both new columns stay NULL — expected,
    not an error."""
    SHOP_ID = "6650guest1234def5678e2dd"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup(session, external_pos_id="ext-drink-2")
        await _make_bar_with_shop(session, tenant.id, ev.id, shop_id=SHOP_ID)

        order = _Order(
            id="o-guest-1",
            cart=[_CartLine(id="l-1", product="ext-drink-2")],
            shop=_Shop(id=SHOP_ID),
            payment=_Payment(type="cash"),
        )
        svc = StockTransactionService(session)
        await ingest_order(
            db=session, order=order, event_id=ev.id, tenant_id=tenant.id, service=svc,
        )
        await session.flush()

        row = await session.scalar(
            select(EventOrder).where(EventOrder.slesh_order_id == "o-guest-1")
        )
        assert row is not None
        assert row.customer_email is None
        assert row.payment_token is None

        await delete_tenant_cascade(session, tenant.id)


async def test_ingest_order_reingest_does_not_clobber_identity_columns():
    """A later poll (e.g. a refund replay) that no longer carries the email
    must not blank out — or overwrite with a different value — what an
    earlier poll already captured. Every other event_orders column keeps
    the existing always-overwrite behavior; only the two identity columns
    are coalesce-only."""
    SHOP_ID = "6650replay1234def5678e2ee"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup(session, external_pos_id="ext-drink-3")
        await _make_bar_with_shop(session, tenant.id, ev.id, shop_id=SHOP_ID)
        svc = StockTransactionService(session)

        first = _Order(
            id="o-replay-1",
            cart=[_CartLine(id="l-1", product="ext-drink-3", status="completed")],
            shop=_Shop(id=SHOP_ID),
            payment=_Payment(type="token", payment_token="tok-original"),
            customer_email="first@example.com",
        )
        await ingest_order(
            db=session, order=first, event_id=ev.id, tenant_id=tenant.id, service=svc,
        )
        await session.flush()

        # Re-poll of the same order: refund status changed on the line, and
        # this time the payload has no email/token (Slesh sometimes omits
        # them on a refund event) plus a DIFFERENT token, to prove coalesce
        # protects the first-seen value either way.
        second = _Order(
            id="o-replay-1",
            cart=[_CartLine(id="l-1", product="ext-drink-3", status="refunded")],
            shop=_Shop(id=SHOP_ID),
            payment=_Payment(type="token", payment_token="tok-different"),
            customer_email=None,
        )
        await ingest_order(
            db=session, order=second, event_id=ev.id, tenant_id=tenant.id, service=svc,
        )
        await session.flush()

        row = await session.scalar(
            select(EventOrder).where(EventOrder.slesh_order_id == "o-replay-1")
        )
        assert row is not None
        assert row.customer_email == "first@example.com", "identity column was clobbered on re-ingest"
        assert row.payment_token == "tok-original", "identity column was overwritten on re-ingest"
        # Sanity: non-identity columns DID update, proving this is a
        # targeted coalesce, not a stuck row.
        assert row.refunded_line_count == 1

        await delete_tenant_cascade(session, tenant.id)


async def test_ingest_order_reingest_fills_previously_null_identity_columns():
    """The inverse of the clobber test: if the FIRST poll had no email/token
    and a LATER poll does, the columns must get populated (not stay NULL
    forever just because they were once empty)."""
    SHOP_ID = "6650fill1234def5678e2ff"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup(session, external_pos_id="ext-drink-4")
        await _make_bar_with_shop(session, tenant.id, ev.id, shop_id=SHOP_ID)
        svc = StockTransactionService(session)

        first = _Order(
            id="o-fill-1",
            cart=[_CartLine(id="l-1", product="ext-drink-4")],
            shop=_Shop(id=SHOP_ID),
            payment=_Payment(type="cash"),
        )
        await ingest_order(
            db=session, order=first, event_id=ev.id, tenant_id=tenant.id, service=svc,
        )
        await session.flush()

        second = _Order(
            id="o-fill-1",
            cart=[_CartLine(id="l-1", product="ext-drink-4")],
            shop=_Shop(id=SHOP_ID),
            payment=_Payment(type="token", payment_token="tok-later"),
            customer_email="later@example.com",
        )
        await ingest_order(
            db=session, order=second, event_id=ev.id, tenant_id=tenant.id, service=svc,
        )
        await session.flush()

        row = await session.scalar(
            select(EventOrder).where(EventOrder.slesh_order_id == "o-fill-1")
        )
        assert row is not None
        assert row.customer_email == "later@example.com"
        assert row.payment_token == "tok-later"

        await delete_tenant_cascade(session, tenant.id)


# ─────────────────────────────────────────────────────────────────────
# Durable per-line ingestion error trace (2026-07-29 hardening)
# ─────────────────────────────────────────────────────────────────────
from app.modules.pos.models import IngestionLineError


async def test_ingest_order_line_failure_persists_durable_error_row(monkeypatch):
    """A per-line exception must not crash ingest_order (unchanged
    behavior) AND must now leave a queryable row in
    ingestion_line_errors — the Jul-5 hardening. Before this, the only
    trace was an in-memory IngestResult.error_messages entry, discarded
    after the poller logged it."""
    SHOP_ID = "6650fail1234def5678e2gg"
    async with TestSessionLocal() as session:
        tenant, ev, prod = await _setup(session, external_pos_id="ext-fail-1")
        await _make_bar_with_shop(session, tenant.id, ev.id, shop_id=SHOP_ID)
        # _persist_line_error writes via a SEPARATE, fresh session (by
        # design — see its docstring), so tenant/event must be durably
        # committed here, not just flushed, or that other connection
        # can't see them yet under READ COMMITTED. In production this is
        # a non-issue: the tenant/event long predate the poll cycle.
        await session.commit()

        svc = StockTransactionService(session)

        async def _boom(*args, **kwargs):
            raise RuntimeError("simulated ingestion failure")
        monkeypatch.setattr(svc, "ingest_sale", _boom)

        order = _Order(
            id="o-fail-1",
            cart=[_CartLine(id="l-fail-1", product="ext-fail-1")],
            shop=_Shop(id=SHOP_ID),
            payment=_Payment(type="cash"),
        )
        result = await ingest_order(
            db=session, order=order, event_id=ev.id, tenant_id=tenant.id, service=svc,
        )
        await session.flush()

        # Existing behavior unchanged: counted as a line error, order not crashed.
        assert result.lines_errors == 1

        # New: a durable, queryable row exists for this exact failure.
        error_row = await session.scalar(
            select(IngestionLineError).where(
                IngestionLineError.slesh_order_id == "o-fail-1",
                IngestionLineError.slesh_line_id == "l-fail-1",
            )
        )
        assert error_row is not None
        assert error_row.tenant_id == tenant.id
        assert error_row.event_id == ev.id
        assert error_row.error_type == "RuntimeError"
        assert "simulated ingestion failure" in error_row.error_message

        # The order-level summary row still gets written — a failed line
        # must not take down the rest of the order.
        eo_row = await session.scalar(
            select(EventOrder).where(EventOrder.slesh_order_id == "o-fail-1")
        )
        assert eo_row is not None

        await delete_tenant_cascade(session, tenant.id)
