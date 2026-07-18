"""DB-level tests for BarService.merge_bars — the no-data-loss merge
that folds auto-created stub bars (which the ingester mints for
unmapped Slesh shop_ids) into properly-named bars.

Covers: happy path (transactions transferred, slesh_negozio_id moved,
post-merge ingest hits dst); slesh_negozio_id conflict refused; merging
into a stub refused; src==dst refused; not-found errors.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.modules.bars.models import Bar
from app.modules.bars.service import (
    BarMergeConflictError,
    BarMergeInvalidError,
    BarNotFoundError,
    BarService,
)
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


async def _make_named_bar(session, tenant_id, event_id, *, name="Cocktail Bar", slesh_id=None, is_active=True):
    bar = Bar(
        tenant_id=tenant_id, event_id=event_id, name=name,
        slesh_negozio_id=slesh_id, bar_type="drinks", is_active=is_active,
        auto_created=False,
    )
    session.add(bar)
    await session.flush()
    return bar


async def _ensure_stub_bar(session, tenant_id, event_id, shop_id: str) -> Bar:
    """Mirrors what order_ingester._resolve_bar used to auto-create for an
    unmapped shop_id (Jul-19 sprint removed that — see order_ingester.py
    and the phantom-bar defensive fix). These merge tests need the stub
    bar to already exist before ingesting a sale against it, since the
    ingester no longer creates one on the fly."""
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


async def _ingest_one_sale(session, tenant_id, event_id, *, shop_id, product_ext, order_id, line_id):
    await _ensure_stub_bar(session, tenant_id, event_id, shop_id)
    svc = StockTransactionService(session)
    order = _Order(
        id=order_id,
        shop=_Shop(id=shop_id),
        cart=[_CartLine(id=line_id, product=product_ext, gross_amount=1500)],
        payment=_Payment(type="card"),
    )
    result = await ingest_order(
        db=session, order=order, event_id=event_id, tenant_id=tenant_id, service=svc,
    )
    await session.flush()
    return result


# ─── Happy path ─────────────────────────────────────────────────────

async def test_merge_stub_into_named_bar_happy_path():
    """Stub bar (auto-created from SHOP_X with 2 sales) folds into a
    properly-named bar that had 0 sales. After merge:
      - stub deleted
      - named bar has both transactions, no orphans
      - slesh_negozio_id transferred from stub to named bar
      - a subsequent ingest for SHOP_X lands on the named bar
        (no new stub created — routing follows the moved slesh_id)
    """
    SHOP_X = "shopXunmappedabcdef1234"
    async with TestSessionLocal() as session:
        tenant, ev, _ = await _setup(session, external_pos_id="prod_A")
        try:
            # 2 sales on auto-created stub via ingester
            await _ingest_one_sale(
                session, tenant.id, ev.id,
                shop_id=SHOP_X, product_ext="prod_A",
                order_id="ord1", line_id="line1",
            )
            await _ingest_one_sale(
                session, tenant.id, ev.id,
                shop_id=SHOP_X, product_ext="prod_A",
                order_id="ord2", line_id="line2",
            )

            stub = (await session.execute(
                select(Bar).where(Bar.slesh_negozio_id == SHOP_X)
            )).scalar_one()
            assert stub.auto_created is True

            named = await _make_named_bar(session, tenant.id, ev.id, name="Cocktail Bar")
            assert named.slesh_negozio_id is None

            svc = BarService(session)
            await svc.merge_bars(tenant.id, stub.id, named.id)

            remaining = (await session.execute(
                select(Bar).where(Bar.tenant_id == tenant.id, Bar.event_id == ev.id)
            )).scalars().all()
            assert len(remaining) == 1
            survivor = remaining[0]
            assert survivor.id == named.id
            assert survivor.name == "Cocktail Bar"
            assert survivor.slesh_negozio_id == SHOP_X
            assert survivor.auto_created is False  # named bar flag preserved
            assert survivor.is_active is True  # merge always activates dst

            tx_on_named = await session.scalar(
                select(func.count()).select_from(StockTransaction).where(
                    StockTransaction.bar_id == named.id
                )
            )
            assert tx_on_named == 2

            tx_total = await session.scalar(
                select(func.count()).select_from(StockTransaction).where(
                    StockTransaction.tenant_id == tenant.id,
                    StockTransaction.event_id == ev.id,
                )
            )
            assert tx_total == 2, "no orphaned transactions"

            # Future Slesh order for SHOP_X lands on named (no new stub)
            await _ingest_one_sale(
                session, tenant.id, ev.id,
                shop_id=SHOP_X, product_ext="prod_A",
                order_id="ord3", line_id="line3",
            )
            bar_count_after = await session.scalar(
                select(func.count()).select_from(Bar).where(
                    Bar.tenant_id == tenant.id, Bar.event_id == ev.id,
                )
            )
            assert bar_count_after == 1, "next order must reuse named bar"
            tx_on_named_after = await session.scalar(
                select(func.count()).select_from(StockTransaction).where(
                    StockTransaction.bar_id == named.id
                )
            )
            assert tx_on_named_after == 3
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


# ─── Refusals ───────────────────────────────────────────────────────

async def test_merge_refuses_when_dst_is_auto_created():
    """Cannot merge INTO another auto-created stub — dst must be named."""
    async with TestSessionLocal() as session:
        tenant, ev, _ = await _setup(session)
        try:
            stub_a = Bar(
                tenant_id=tenant.id, event_id=ev.id, name="stubA",
                slesh_negozio_id="shopA", bar_type="drinks",
                is_active=True, auto_created=True,
            )
            stub_b = Bar(
                tenant_id=tenant.id, event_id=ev.id, name="stubB",
                slesh_negozio_id="shopB", bar_type="drinks",
                is_active=True, auto_created=True,
            )
            session.add_all([stub_a, stub_b])
            await session.flush()

            svc = BarService(session)
            with pytest.raises(BarMergeConflictError, match="auto-created"):
                await svc.merge_bars(tenant.id, stub_a.id, stub_b.id)
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_merge_refuses_when_src_equals_dst():
    async with TestSessionLocal() as session:
        tenant, ev, _ = await _setup(session)
        try:
            bar = await _make_named_bar(session, tenant.id, ev.id)
            svc = BarService(session)
            with pytest.raises(BarMergeInvalidError, match="must differ"):
                await svc.merge_bars(tenant.id, bar.id, bar.id)
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_merge_refuses_slesh_id_conflict():
    """Both bars already mapped to (different) Slesh shops — refuse."""
    async with TestSessionLocal() as session:
        tenant, ev, _ = await _setup(session)
        try:
            stub = Bar(
                tenant_id=tenant.id, event_id=ev.id, name="stub",
                slesh_negozio_id="shopA", bar_type="drinks",
                is_active=True, auto_created=True,
            )
            session.add(stub)
            named = await _make_named_bar(
                session, tenant.id, ev.id,
                name="Already Mapped", slesh_id="shopB",
            )
            await session.flush()

            svc = BarService(session)
            with pytest.raises(BarMergeConflictError, match="already mapped"):
                await svc.merge_bars(tenant.id, stub.id, named.id)
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_merge_refuses_when_src_not_found():
    async with TestSessionLocal() as session:
        tenant, ev, _ = await _setup(session)
        try:
            named = await _make_named_bar(session, tenant.id, ev.id)
            svc = BarService(session)
            with pytest.raises(BarNotFoundError):
                await svc.merge_bars(tenant.id, uuid4(), named.id)
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_merge_activates_inactive_dst():
    """Wine Station scenario: a wizard bar placed but never activated
    (is_active=False) gets a Slesh shop_id merged in. The merge MUST
    flip is_active to True so the dashboard surfaces the bar with its
    incoming revenue. Without this, the merged bar stays hidden behind
    the is_active=False filter and Slesh sales are silently dropped
    from the UI.
    """
    SHOP_X = "shopXinactivedst1234abcd"
    async with TestSessionLocal() as session:
        tenant, ev, _ = await _setup(session, external_pos_id="prod_A")
        try:
            await _ingest_one_sale(
                session, tenant.id, ev.id,
                shop_id=SHOP_X, product_ext="prod_A",
                order_id="ord1", line_id="line1",
            )
            stub = (await session.execute(
                select(Bar).where(Bar.slesh_negozio_id == SHOP_X)
            )).scalar_one()
            # Inactive wizard bar (e.g. Wine Station unused this event)
            wine = await _make_named_bar(
                session, tenant.id, ev.id,
                name="Wine Station", is_active=False,
            )
            assert wine.is_active is False
            svc = BarService(session)
            survivor = await svc.merge_bars(tenant.id, stub.id, wine.id)
            assert survivor.id == wine.id
            assert survivor.is_active is True, (
                "merge must activate dst — otherwise the merged bar "
                "stays hidden and Slesh revenue is silently dropped"
            )
            assert survivor.slesh_negozio_id == SHOP_X
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()
