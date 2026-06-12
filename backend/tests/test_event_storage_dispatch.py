"""DB-level tests for the event_stock_bar_allocations dispatch flow.

Covers commit 2 of the Phase 2.5 warehouse + inventory rewrite:
  - create_dispatch       (single row, tenant/event/bar validation)
  - bulk_create_dispatches (atomic, all-or-nothing)
  - list_activity_feed    (joined names, ordered desc, limit honored)
  - list_bar_allocations  (per-bar grouped totals)
  - storage summary reflects allocations once dispatches land

History-preserving semantics: re-dispatching to the same
(supplier_product, bar) creates a NEW row rather than upserting.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.modules.bars.models import Bar
from app.modules.event_storage.models import (
    EventStockBarAllocation,
    EventStockItem,
    SupplierProduct,
)
from app.modules.event_storage.schemas import (
    DispatchCreate,
    EventStockItemCreate,
)
from app.modules.event_storage.service import (
    BarNotFoundError,
    EventStorageService,
    SupplierProductNotFoundError,
)
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_event,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


# ─── Helpers ─────────────────────────────────────────────────────────


async def _make_supplier_product(
    session, tenant_id: UUID, *,
    supplier_sku: str | None = None,
    item_name: str = "BEEFEATER LONDON DRY 1LT GIN",
    category: str = "gin",
) -> SupplierProduct:
    sp = SupplierProduct(
        tenant_id=tenant_id,
        supplier_name="Partesa",
        supplier_sku=supplier_sku or f"SKU-{uuid4().hex[:8]}",
        item_name=item_name,
        category=category,
        default_unit="BO",
        units_per_pack=1,
        volume_per_unit_ml=1000,
        last_unit_price_eur=Decimal("26.20"),
    )
    session.add(sp)
    await session.flush()
    return sp


async def _make_bar(
    session, tenant_id: UUID, event_id: UUID, *,
    name: str = "Cocktail Bar",
) -> Bar:
    bar = Bar(
        tenant_id=tenant_id,
        event_id=event_id,
        name=name,
        bar_type="cocktail",
        is_active=True,
        device_count=2,
        auto_created=False,
    )
    session.add(bar)
    await session.flush()
    return bar


async def _make_event_stock_item(
    session, svc: EventStorageService, tenant_id: UUID, event_id: UUID,
    supplier_product_id: UUID, qty_received: Decimal = Decimal("100"),
):
    """Helper to seed event_stock_items so we can later check that
    dispatches subtract from the available pool."""
    await svc.bulk_upsert_event_stock_items(
        tenant_id, event_id,
        [EventStockItemCreate(
            supplier_product_id=supplier_product_id,
            qty_received=qty_received,
            unit="BO",
            unit_price_eur=Decimal("26.20"),
        )],
    )


# ─── create_dispatch ─────────────────────────────────────────────────


async def test_create_dispatch_persists_row():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status="DRAFT")
            svc = EventStorageService(session)
            sp = await _make_supplier_product(session, tenant.id)
            bar = await _make_bar(session, tenant.id, event.id)
            await session.flush()

            row = await svc.create_dispatch(
                tenant.id, event.id,
                DispatchCreate(
                    supplier_product_id=sp.id,
                    bar_id=bar.id,
                    qty_allocated=Decimal("50"),
                    notes="first delivery",
                ),
            )

            assert row.id is not None
            assert row.tenant_id == tenant.id
            assert row.event_id == event.id
            assert row.supplier_product_id == sp.id
            assert row.bar_id == bar.id
            assert row.qty_allocated == Decimal("50")
            assert row.notes == "first delivery"
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_create_dispatch_rejects_cross_tenant_supplier_product():
    async with TestSessionLocal() as session:
        tenant_a = await make_tenant(session)
        tenant_b = await make_tenant(session)
        try:
            event_a = await make_event(session, tenant_a.id, status="DRAFT")
            sp_b = await _make_supplier_product(session, tenant_b.id)
            bar_a = await _make_bar(session, tenant_a.id, event_a.id)
            await session.flush()

            svc = EventStorageService(session)
            with pytest.raises(SupplierProductNotFoundError):
                await svc.create_dispatch(
                    tenant_a.id, event_a.id,
                    DispatchCreate(
                        supplier_product_id=sp_b.id,  # wrong tenant
                        bar_id=bar_a.id,
                        qty_allocated=Decimal("10"),
                    ),
                )
        finally:
            await delete_tenant_cascade(session, tenant_a.id)
            await delete_tenant_cascade(session, tenant_b.id)


async def test_create_dispatch_rejects_bar_from_different_event():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event_a = await make_event(session, tenant.id, status="DRAFT")
            event_b = await make_event(session, tenant.id, status="DRAFT")
            svc = EventStorageService(session)
            sp = await _make_supplier_product(session, tenant.id)
            bar_b = await _make_bar(session, tenant.id, event_b.id)
            await session.flush()

            with pytest.raises(BarNotFoundError):
                await svc.create_dispatch(
                    tenant.id, event_a.id,  # different event
                    DispatchCreate(
                        supplier_product_id=sp.id,
                        bar_id=bar_b.id,
                        qty_allocated=Decimal("10"),
                    ),
                )
        finally:
            await delete_tenant_cascade(session, tenant.id)


# ─── bulk_create_dispatches ──────────────────────────────────────────


async def test_bulk_create_dispatches_atomic_success():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status="DRAFT")
            svc = EventStorageService(session)
            sp1 = await _make_supplier_product(session, tenant.id, item_name="GIN")
            sp2 = await _make_supplier_product(session, tenant.id, item_name="VODKA")
            bar1 = await _make_bar(session, tenant.id, event.id, name="Bar1")
            bar2 = await _make_bar(session, tenant.id, event.id, name="Bar2")
            await session.flush()

            rows = await svc.bulk_create_dispatches(
                tenant.id, event.id,
                [
                    DispatchCreate(supplier_product_id=sp1.id, bar_id=bar1.id,
                                   qty_allocated=Decimal("10")),
                    DispatchCreate(supplier_product_id=sp2.id, bar_id=bar1.id,
                                   qty_allocated=Decimal("5")),
                    DispatchCreate(supplier_product_id=sp1.id, bar_id=bar2.id,
                                   qty_allocated=Decimal("3")),
                ],
            )
            assert len(rows) == 3
            assert {r.qty_allocated for r in rows} == {
                Decimal("10"), Decimal("5"), Decimal("3"),
            }
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_bulk_create_dispatches_rolls_back_on_invalid_bar():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status="DRAFT")
            svc = EventStorageService(session)
            sp = await _make_supplier_product(session, tenant.id)
            bar_ok = await _make_bar(session, tenant.id, event.id)
            await session.flush()

            bogus_bar_id = uuid4()
            with pytest.raises(BarNotFoundError):
                await svc.bulk_create_dispatches(
                    tenant.id, event.id,
                    [
                        DispatchCreate(supplier_product_id=sp.id,
                                       bar_id=bar_ok.id,
                                       qty_allocated=Decimal("10")),
                        DispatchCreate(supplier_product_id=sp.id,
                                       bar_id=bogus_bar_id,
                                       qty_allocated=Decimal("5")),
                    ],
                )
            # Atomic: neither row should have been inserted
            from sqlalchemy import select, func
            count = (await session.execute(
                select(func.count(EventStockBarAllocation.id))
                .where(EventStockBarAllocation.event_id == event.id)
            )).scalar_one()
            assert count == 0
        finally:
            await delete_tenant_cascade(session, tenant.id)


# ─── history-preserving ──────────────────────────────────────────────


async def test_history_preserving_same_pair_creates_separate_rows():
    """Re-dispatching the same (supplier_product, bar) pair must
    create a NEW row, not upsert — so activity feed has full history."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status="DRAFT")
            svc = EventStorageService(session)
            sp = await _make_supplier_product(session, tenant.id)
            bar = await _make_bar(session, tenant.id, event.id)
            await session.flush()

            r1 = await svc.create_dispatch(
                tenant.id, event.id,
                DispatchCreate(supplier_product_id=sp.id, bar_id=bar.id,
                               qty_allocated=Decimal("10")),
            )
            r2 = await svc.create_dispatch(
                tenant.id, event.id,
                DispatchCreate(supplier_product_id=sp.id, bar_id=bar.id,
                               qty_allocated=Decimal("7")),
            )
            assert r1.id != r2.id
        finally:
            await delete_tenant_cascade(session, tenant.id)


# ─── list_activity_feed ──────────────────────────────────────────────


async def test_list_activity_feed_orders_newest_first_with_joined_names():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status="DRAFT")
            svc = EventStorageService(session)
            sp_gin = await _make_supplier_product(
                session, tenant.id, item_name="GIN")
            sp_vodka = await _make_supplier_product(
                session, tenant.id, item_name="VODKA")
            bar = await _make_bar(session, tenant.id, event.id,
                                   name="Cocktail Bar")
            await session.flush()

            # Two dispatches, vodka second
            await svc.create_dispatch(
                tenant.id, event.id,
                DispatchCreate(supplier_product_id=sp_gin.id, bar_id=bar.id,
                               qty_allocated=Decimal("10")),
            )
            await svc.create_dispatch(
                tenant.id, event.id,
                DispatchCreate(supplier_product_id=sp_vodka.id, bar_id=bar.id,
                               qty_allocated=Decimal("4")),
            )

            feed = await svc.list_activity_feed(tenant.id, event.id)
            assert len(feed) == 2
            # Newest first → vodka
            assert feed[0].item_name == "VODKA"
            assert feed[1].item_name == "GIN"
            # Joined fields are populated
            assert feed[0].bar_name == "Cocktail Bar"
            assert feed[0].item_unit == "BO"
            # No user attribution → None
            assert feed[0].user_name is None
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_list_activity_feed_respects_limit():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status="DRAFT")
            svc = EventStorageService(session)
            sp = await _make_supplier_product(session, tenant.id)
            bar = await _make_bar(session, tenant.id, event.id)
            await session.flush()

            for _ in range(5):
                await svc.create_dispatch(
                    tenant.id, event.id,
                    DispatchCreate(supplier_product_id=sp.id, bar_id=bar.id,
                                   qty_allocated=Decimal("1")),
                )

            feed = await svc.list_activity_feed(tenant.id, event.id, limit=3)
            assert len(feed) == 3
        finally:
            await delete_tenant_cascade(session, tenant.id)


# ─── list_bar_allocations ────────────────────────────────────────────


async def test_list_bar_allocations_groups_and_sums_per_bar():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status="DRAFT")
            svc = EventStorageService(session)
            sp_gin = await _make_supplier_product(
                session, tenant.id, item_name="GIN")
            sp_vodka = await _make_supplier_product(
                session, tenant.id, item_name="VODKA")
            bar1 = await _make_bar(session, tenant.id, event.id, name="A-Bar")
            bar2 = await _make_bar(session, tenant.id, event.id, name="B-Bar")
            await session.flush()

            # Bar1: 10 + 5 GIN = 15 total GIN, plus 3 VODKA
            await svc.create_dispatch(tenant.id, event.id,
                DispatchCreate(supplier_product_id=sp_gin.id, bar_id=bar1.id,
                               qty_allocated=Decimal("10")))
            await svc.create_dispatch(tenant.id, event.id,
                DispatchCreate(supplier_product_id=sp_gin.id, bar_id=bar1.id,
                               qty_allocated=Decimal("5")))
            await svc.create_dispatch(tenant.id, event.id,
                DispatchCreate(supplier_product_id=sp_vodka.id, bar_id=bar1.id,
                               qty_allocated=Decimal("3")))
            # Bar2: 7 GIN
            await svc.create_dispatch(tenant.id, event.id,
                DispatchCreate(supplier_product_id=sp_gin.id, bar_id=bar2.id,
                               qty_allocated=Decimal("7")))

            grouped = await svc.list_bar_allocations(tenant.id, event.id)
            assert len(grouped) == 2
            by_name = {g.bar_name: g for g in grouped}

            # Bar1: GIN should be 15 (summed), VODKA 3
            bar1_items = {i.item_name: i.qty_total_allocated
                          for i in by_name["A-Bar"].items}
            assert bar1_items == {"GIN": Decimal("15"), "VODKA": Decimal("3")}
            # Bar2: GIN 7 only
            bar2_items = {i.item_name: i.qty_total_allocated
                          for i in by_name["B-Bar"].items}
            assert bar2_items == {"GIN": Decimal("7")}
        finally:
            await delete_tenant_cascade(session, tenant.id)


# ─── storage summary reflects dispatches ─────────────────────────────


async def test_storage_summary_reflects_dispatches():
    """After dispatching from the pool, qty_allocated should rise and
    qty_available should fall on the StorageSummaryRow."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status="DRAFT")
            svc = EventStorageService(session)
            sp = await _make_supplier_product(session, tenant.id)
            bar = await _make_bar(session, tenant.id, event.id)
            await session.flush()

            # Pool: 100 received
            await _make_event_stock_item(
                session, svc, tenant.id, event.id, sp.id,
                qty_received=Decimal("100"),
            )
            # Dispatch 40 to the bar
            await svc.create_dispatch(
                tenant.id, event.id,
                DispatchCreate(supplier_product_id=sp.id, bar_id=bar.id,
                               qty_allocated=Decimal("40")),
            )

            summary = await svc.get_storage_summary(tenant.id, event.id)
            assert summary.total_qty_received == Decimal("100")
            assert summary.total_qty_allocated == Decimal("40")
            assert len(summary.rows) == 1
            row = summary.rows[0]
            assert row.qty_received == Decimal("100")
            assert row.qty_allocated == Decimal("40")
            assert row.qty_available == Decimal("60")
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_list_activity_feed_filtered_by_bar_id():
    """When bar_id is passed, only that bar's dispatches come back."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status="DRAFT")
            svc = EventStorageService(session)
            sp = await _make_supplier_product(session, tenant.id)
            bar_a = await _make_bar(session, tenant.id, event.id, name="A")
            bar_b = await _make_bar(session, tenant.id, event.id, name="B")
            await session.flush()

            await svc.create_dispatch(tenant.id, event.id,
                DispatchCreate(supplier_product_id=sp.id, bar_id=bar_a.id,
                               qty_allocated=Decimal("10")))
            await svc.create_dispatch(tenant.id, event.id,
                DispatchCreate(supplier_product_id=sp.id, bar_id=bar_b.id,
                               qty_allocated=Decimal("5")))

            global_feed = await svc.list_activity_feed(tenant.id, event.id)
            assert len(global_feed) == 2

            a_feed = await svc.list_activity_feed(
                tenant.id, event.id, bar_id=bar_a.id,
            )
            assert len(a_feed) == 1
            assert a_feed[0].bar_name == "A"
            assert a_feed[0].qty_allocated == Decimal("10")
        finally:
            await delete_tenant_cascade(session, tenant.id)

