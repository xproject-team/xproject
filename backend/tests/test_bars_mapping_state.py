"""DB-level tests for BarService.get_mapping_state — the three-region
mapping view backing the dashboard's empty / stub / mapped UI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import select

from app.modules.bars.models import Bar
from app.modules.bars.service import BarService, EventNotFoundForBarError
from app.modules.pos.order_ingester import ingest_order
from app.modules.products.models import ProductType
from app.modules.stock_transactions.service import StockTransactionService
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_event,
    make_product,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


# Minimal Slesh order shape (ingester reads attributes only).
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
    product: str
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


async def _setup(session, *, external_pos_id: str = "prod_A"):
    tenant = await make_tenant(session)
    ev = await make_event(session, tenant.id)
    prod = await make_product(session, tenant.id, product_type=ProductType.DRINK)
    prod.external_pos_id = external_pos_id
    prod.default_price_cents = 1500
    await session.flush()
    return tenant, ev, prod


async def _make_named_bar(session, tenant_id, event_id, *, name, bar_type="drinks", device_count=0, slesh_id=None):
    bar = Bar(
        tenant_id=tenant_id, event_id=event_id, name=name,
        bar_type=bar_type, device_count=device_count,
        slesh_negozio_id=slesh_id, is_active=True,
        auto_created=False,
    )
    session.add(bar)
    await session.flush()
    return bar


async def _ensure_stub_bar(session, tenant_id, event_id, shop_id: str) -> Bar:
    """Mirrors what order_ingester._resolve_bar used to auto-create for an
    unmapped shop_id (Jul-19 sprint removed that — see order_ingester.py).
    These tests need a 'stub' bar (auto_created=True, no wizard name) to
    exist BEFORE ingesting sales against it, since the ingester no longer
    creates one on the fly."""
    existing = (await session.execute(
        select(Bar).where(Bar.tenant_id == tenant_id, Bar.slesh_negozio_id == shop_id)
    )).scalar_one_or_none()
    if existing is not None:
        return existing
    display = f"{shop_id[:8]}…{shop_id[-4:]}" if len(shop_id) > 12 else shop_id
    bar = Bar(
        tenant_id=tenant_id, event_id=event_id, name=display,
        slesh_negozio_id=shop_id, bar_type="drinks",
        is_active=True, auto_created=True,
    )
    session.add(bar)
    await session.flush()
    return bar


async def _ingest_sales(session, tenant_id, event_id, *, shop_id, prod_ext, n):
    await _ensure_stub_bar(session, tenant_id, event_id, shop_id)
    svc = StockTransactionService(session)
    for i in range(n):
        order = _Order(
            id=f"{shop_id}-ord{i}",
            shop=_Shop(id=shop_id),
            cart=[_CartLine(id=f"{shop_id}-line{i}", product=prod_ext, gross_amount=1500)],
            payment=_Payment(type="card"),
        )
        await ingest_order(
            db=session, order=order, event_id=event_id, tenant_id=tenant_id, service=svc,
        )
    await session.flush()


# ─── Tests ──────────────────────────────────────────────────────────

async def test_mapping_state_empty_event():
    """Event with no bars at all → all three lists empty."""
    async with TestSessionLocal() as session:
        tenant, ev, _ = await _setup(session)
        try:
            svc = BarService(session)
            state = await svc.get_mapping_state(tenant.id, ev.id)
            assert state["empty_bars"] == []
            assert state["stubs"] == []
            assert state["mapped_bars"] == []
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_mapping_state_only_empty_wizard_bars():
    """Three wizard bars, no transactions yet → all three sit in empty_bars,
    sorted by device_count desc."""
    async with TestSessionLocal() as session:
        tenant, ev, _ = await _setup(session)
        try:
            await _make_named_bar(session, tenant.id, ev.id, name="Beer Bar",     device_count=4)
            await _make_named_bar(session, tenant.id, ev.id, name="Cocktail Bar", device_count=12)
            await _make_named_bar(session, tenant.id, ev.id, name="Wine Bar",     device_count=6)
            svc = BarService(session)
            state = await svc.get_mapping_state(tenant.id, ev.id)

            assert len(state["empty_bars"]) == 3
            # device_count desc → Cocktail (12), Wine (6), Beer (4)
            assert [b.name for b in state["empty_bars"]] == ["Cocktail Bar", "Wine Bar", "Beer Bar"]
            assert state["stubs"] == []
            assert state["mapped_bars"] == []
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_mapping_state_stub_with_sales_count_and_suggestion():
    """Two empty wizard bars + two stubs of the same bar_type.
    Pairing: highest-sales stub → highest-device empty bar."""
    SHOP_HIGH = "shop_high_sales_24charssss"
    SHOP_LOW  = "shop_low_sales_24chars_aaaa"
    async with TestSessionLocal() as session:
        tenant, ev, _ = await _setup(session, external_pos_id="prod_A")
        try:
            big = await _make_named_bar(
                session, tenant.id, ev.id, name="Cocktail Bar", device_count=12,
            )
            small = await _make_named_bar(
                session, tenant.id, ev.id, name="Wine Bar", device_count=4,
            )

            # Stub with 5 sales (high), stub with 1 sale (low)
            await _ingest_sales(session, tenant.id, ev.id, shop_id=SHOP_HIGH, prod_ext="prod_A", n=5)
            await _ingest_sales(session, tenant.id, ev.id, shop_id=SHOP_LOW,  prod_ext="prod_A", n=1)

            svc = BarService(session)
            state = await svc.get_mapping_state(tenant.id, ev.id)

            assert len(state["empty_bars"]) == 2
            assert len(state["stubs"]) == 2
            assert state["mapped_bars"] == []

            # Stubs sorted by sales_count desc
            top_stub, low_stub = state["stubs"]
            assert top_stub["sales_count"] == 5
            assert low_stub["sales_count"] == 1
            assert top_stub["slesh_negozio_id"] == SHOP_HIGH
            assert low_stub["slesh_negozio_id"] == SHOP_LOW

            # Pairing: top_stub → big (12 devices), low_stub → small (4 devices)
            assert top_stub["suggested_target_bar_id"] == big.id
            assert low_stub["suggested_target_bar_id"] == small.id
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_mapping_state_suggestion_respects_bar_type():
    """Drinks stub paired only with drinks empty; food stub only with food."""
    SHOP_DRINK = "shop_drinks_24_chars_aaaaa"
    async with TestSessionLocal() as session:
        tenant, ev, _ = await _setup(session, external_pos_id="prod_DRK")
        try:
            drinks_empty = await _make_named_bar(
                session, tenant.id, ev.id, name="Cocktail Bar", bar_type="drinks", device_count=8,
            )
            await _make_named_bar(
                session, tenant.id, ev.id, name="Pizza Truck", bar_type="food", device_count=20,
            )

            # One drinks stub
            await _ingest_sales(session, tenant.id, ev.id, shop_id=SHOP_DRINK, prod_ext="prod_DRK", n=3)

            svc = BarService(session)
            state = await svc.get_mapping_state(tenant.id, ev.id)

            assert len(state["stubs"]) == 1
            stub = state["stubs"][0]
            # Despite food empty having higher device_count, drinks stub is
            # paired with the drinks empty (same bar_type rule).
            assert stub["suggested_target_bar_id"] == drinks_empty.id
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_mapping_state_no_empty_left_yields_null_suggestion():
    """Two stubs of same type but only one empty → second stub's
    suggestion is None."""
    SHOP_A = "shop_aaaa_24_chars_aaaaaa"
    SHOP_B = "shop_bbbb_24_chars_bbbbbb"
    async with TestSessionLocal() as session:
        tenant, ev, _ = await _setup(session, external_pos_id="prod_A")
        try:
            only_empty = await _make_named_bar(
                session, tenant.id, ev.id, name="Cocktail Bar", device_count=10,
            )
            await _ingest_sales(session, tenant.id, ev.id, shop_id=SHOP_A, prod_ext="prod_A", n=5)
            await _ingest_sales(session, tenant.id, ev.id, shop_id=SHOP_B, prod_ext="prod_A", n=2)

            svc = BarService(session)
            state = await svc.get_mapping_state(tenant.id, ev.id)

            assert len(state["empty_bars"]) == 1
            assert len(state["stubs"]) == 2

            top_stub, second_stub = state["stubs"]
            assert top_stub["sales_count"] == 5
            assert second_stub["sales_count"] == 2
            assert top_stub["suggested_target_bar_id"] == only_empty.id
            assert second_stub["suggested_target_bar_id"] is None
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_mapping_state_mapped_bars_bucket():
    """A named bar with slesh_negozio_id (already mapped, auto_created=False)
    appears in mapped_bars and not in empty_bars or stubs."""
    async with TestSessionLocal() as session:
        tenant, ev, _ = await _setup(session)
        try:
            await _make_named_bar(
                session, tenant.id, ev.id, name="Beer Bar", slesh_id="shop_already_mapped",
            )
            await _make_named_bar(
                session, tenant.id, ev.id, name="Wine Bar", device_count=4,
            )

            svc = BarService(session)
            state = await svc.get_mapping_state(tenant.id, ev.id)

            assert len(state["mapped_bars"]) == 1
            assert state["mapped_bars"][0].name == "Beer Bar"
            assert len(state["empty_bars"]) == 1
            assert state["empty_bars"][0].name == "Wine Bar"
            assert state["stubs"] == []
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_mapping_state_404_on_missing_event():
    from uuid import uuid4
    async with TestSessionLocal() as session:
        tenant, _, _ = await _setup(session)
        try:
            svc = BarService(session)
            with pytest.raises(EventNotFoundForBarError):
                await svc.get_mapping_state(tenant.id, uuid4())
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()
