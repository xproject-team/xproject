"""DB-level tests for EventStorageService — Phase 2 commit 2.

Covers the master-list upsert behavior, bulk event-stock upsert with
existing/new row mixing, validation that supplier_products belong to
the tenant, last-price refresh side effect, and the summary aggregation.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.modules.event_storage.models import EventStockItem, SupplierProduct
from app.modules.event_storage.schemas import EventStockItemCreate
from app.modules.event_storage.service import (
    EventStockItemNotFoundError,
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
    supplier_sku: str = "2193T",
    item_name: str = "BEEFEATER LONDON DRY 1LT GIN",
    category: str = "gin",
    default_unit: str = "BO",
    units_per_pack: int = 1,
    volume_per_unit_ml: int | None = 1000,
    last_unit_price_eur: Decimal | None = Decimal("26.20"),
) -> SupplierProduct:
    sp = SupplierProduct(
        tenant_id=tenant_id,
        supplier_name="Partesa",
        supplier_sku=supplier_sku,
        item_name=item_name,
        category=category,
        default_unit=default_unit,
        units_per_pack=units_per_pack,
        volume_per_unit_ml=volume_per_unit_ml,
        last_unit_price_eur=last_unit_price_eur,
    )
    session.add(sp)
    await session.flush()
    return sp


# ─── Supplier product upsert ─────────────────────────────────────────

async def test_upsert_creates_new_supplier_product():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            svc = EventStorageService(session)
            sp = await svc.upsert_supplier_product(
                tenant.id,
                supplier_sku="2193T",
                item_name="BEEFEATER LONDON DRY 1LT GIN",
                category="gin",
                default_unit="BO",
                volume_per_unit_ml=1000,
                last_unit_price_eur=Decimal("26.20"),
            )
            assert sp.id is not None
            assert sp.tenant_id == tenant.id
            assert sp.supplier_sku == "2193T"
            assert sp.category == "gin"
            assert sp.last_unit_price_eur == Decimal("26.20")
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_upsert_refreshes_price_on_existing():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            svc = EventStorageService(session)
            sp1 = await svc.upsert_supplier_product(
                tenant.id,
                supplier_sku="2193T",
                item_name="BEEFEATER LONDON DRY 1LT GIN",
                category="gin",
                default_unit="BO",
                last_unit_price_eur=Decimal("26.20"),
            )
            sp2 = await svc.upsert_supplier_product(
                tenant.id,
                supplier_sku="2193T",
                item_name="BEEFEATER LONDON DRY 1LT GIN",
                category="gin",
                default_unit="BO",
                last_unit_price_eur=Decimal("27.50"),
            )
            assert sp1.id == sp2.id, "must be the same row"
            assert sp2.last_unit_price_eur == Decimal("27.50")
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_list_supplier_products_filtered_by_category():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            await _make_supplier_product(
                session, tenant.id, supplier_sku="2193T",
                item_name="Beefeater Gin", category="gin",
            )
            await _make_supplier_product(
                session, tenant.id, supplier_sku="2034T",
                item_name="Wyborowa Vodka", category="vodka",
            )
            svc = EventStorageService(session)
            gins = await svc.list_supplier_products(tenant.id, category="gin")
            assert len(gins) == 1
            assert gins[0].supplier_sku == "2193T"
            all_items = await svc.list_supplier_products(tenant.id)
            assert len(all_items) == 2
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


# ─── Bulk upsert event stock items ──────────────────────────────────

async def test_bulk_upsert_inserts_new_rows():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        ev = await make_event(session, tenant.id)
        try:
            sp_gin = await _make_supplier_product(
                session, tenant.id, supplier_sku="2193T",
                item_name="Beefeater Gin", category="gin",
            )
            sp_tonica = await _make_supplier_product(
                session, tenant.id, supplier_sku="4262T",
                item_name="Schweppes Tonica 1L", category="mixer",
                default_unit="KAR",
            )
            svc = EventStorageService(session)
            items = [
                EventStockItemCreate(
                    supplier_product_id=sp_gin.id,
                    qty_received=Decimal("240"),
                    unit="BO",
                    unit_price_eur=Decimal("26.20"),
                    line_total_eur=Decimal("3833.16"),
                ),
                EventStockItemCreate(
                    supplier_product_id=sp_tonica.id,
                    qty_received=Decimal("80"),
                    unit="KAR",
                    unit_price_eur=Decimal("21.50"),
                    line_total_eur=Decimal("864.13"),
                ),
            ]
            rows = await svc.bulk_upsert_event_stock_items(
                tenant.id, ev.id, items,
            )
            assert len(rows) == 2
            assert {r.supplier_product_id for r in rows} == {sp_gin.id, sp_tonica.id}
            gin_row = next(r for r in rows if r.supplier_product_id == sp_gin.id)
            assert gin_row.qty_received == Decimal("240")
            assert gin_row.line_total_eur == Decimal("3833.16")
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_bulk_upsert_updates_existing_rows():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        ev = await make_event(session, tenant.id)
        try:
            sp = await _make_supplier_product(session, tenant.id)
            svc = EventStorageService(session)
            await svc.bulk_upsert_event_stock_items(
                tenant.id, ev.id,
                [EventStockItemCreate(
                    supplier_product_id=sp.id,
                    qty_received=Decimal("100"),
                    unit="BO",
                )],
            )
            # Re-submit with a different qty for the SAME supplier_product
            rows = await svc.bulk_upsert_event_stock_items(
                tenant.id, ev.id,
                [EventStockItemCreate(
                    supplier_product_id=sp.id,
                    qty_received=Decimal("250"),
                    unit="BO",
                )],
            )
            assert len(rows) == 1
            assert rows[0].qty_received == Decimal("250")
            # No duplicate row created
            all_rows = await svc.list_event_stock_items(tenant.id, ev.id)
            assert len(all_rows) == 1
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_bulk_upsert_refreshes_last_unit_price_on_supplier_product():
    """Side effect: when an event_stock_item carries a unit_price_eur,
    the supplier_product's last_unit_price_eur is updated to that value
    so the wizard's prefill stays current for the next event."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        ev = await make_event(session, tenant.id)
        try:
            sp = await _make_supplier_product(
                session, tenant.id, last_unit_price_eur=Decimal("26.20"),
            )
            svc = EventStorageService(session)
            await svc.bulk_upsert_event_stock_items(
                tenant.id, ev.id,
                [EventStockItemCreate(
                    supplier_product_id=sp.id,
                    qty_received=Decimal("240"),
                    unit="BO",
                    unit_price_eur=Decimal("28.50"),
                )],
            )
            await session.refresh(sp)
            assert sp.last_unit_price_eur == Decimal("28.50")
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_bulk_upsert_raises_for_unknown_supplier_product():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        ev = await make_event(session, tenant.id)
        try:
            svc = EventStorageService(session)
            bogus_id = uuid4()
            with pytest.raises(SupplierProductNotFoundError) as exc:
                await svc.bulk_upsert_event_stock_items(
                    tenant.id, ev.id,
                    [EventStockItemCreate(
                        supplier_product_id=bogus_id,
                        qty_received=Decimal("10"),
                        unit="BO",
                    )],
                )
            assert exc.value.supplier_product_id == bogus_id
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_bulk_upsert_raises_for_cross_tenant_supplier_product():
    """A tenant cannot reference another tenant's supplier_product."""
    async with TestSessionLocal() as session:
        tenant_a = await make_tenant(session)
        tenant_b = await make_tenant(session)
        ev_a = await make_event(session, tenant_a.id)
        try:
            sp_b = await _make_supplier_product(session, tenant_b.id)
            svc = EventStorageService(session)
            with pytest.raises(SupplierProductNotFoundError):
                await svc.bulk_upsert_event_stock_items(
                    tenant_a.id, ev_a.id,
                    [EventStockItemCreate(
                        supplier_product_id=sp_b.id,
                        qty_received=Decimal("10"),
                        unit="BO",
                    )],
                )
        finally:
            await delete_tenant_cascade(session, tenant_a.id)
            await delete_tenant_cascade(session, tenant_b.id)
            await session.commit()


async def test_delete_event_stock_item():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        ev = await make_event(session, tenant.id)
        try:
            sp = await _make_supplier_product(session, tenant.id)
            svc = EventStorageService(session)
            rows = await svc.bulk_upsert_event_stock_items(
                tenant.id, ev.id,
                [EventStockItemCreate(
                    supplier_product_id=sp.id,
                    qty_received=Decimal("10"),
                    unit="BO",
                )],
            )
            row_id = rows[0].id
            await svc.delete_event_stock_item(tenant.id, row_id)
            remaining = await svc.list_event_stock_items(tenant.id, ev.id)
            assert len(remaining) == 0
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_delete_event_stock_item_404():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            svc = EventStorageService(session)
            with pytest.raises(EventStockItemNotFoundError):
                await svc.delete_event_stock_item(tenant.id, uuid4())
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


# ─── Summary aggregation ────────────────────────────────────────────

async def test_storage_summary_aggregates_by_category_with_totals():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        ev = await make_event(session, tenant.id)
        try:
            sp_gin = await _make_supplier_product(
                session, tenant.id, supplier_sku="2193T",
                item_name="Beefeater Gin", category="gin",
            )
            sp_vodka = await _make_supplier_product(
                session, tenant.id, supplier_sku="2034T",
                item_name="Wyborowa Vodka", category="vodka",
            )
            sp_tonica = await _make_supplier_product(
                session, tenant.id, supplier_sku="4262T",
                item_name="Schweppes Tonica", category="mixer",
                default_unit="KAR",
            )
            svc = EventStorageService(session)
            await svc.bulk_upsert_event_stock_items(
                tenant.id, ev.id,
                [
                    EventStockItemCreate(
                        supplier_product_id=sp_gin.id,
                        qty_received=Decimal("240"), unit="BO",
                        line_total_eur=Decimal("3833.16"),
                    ),
                    EventStockItemCreate(
                        supplier_product_id=sp_vodka.id,
                        qty_received=Decimal("30"), unit="BO",
                        line_total_eur=Decimal("390.04"),
                    ),
                    EventStockItemCreate(
                        supplier_product_id=sp_tonica.id,
                        qty_received=Decimal("80"), unit="KAR",
                        line_total_eur=Decimal("864.13"),
                    ),
                ],
            )
            summary = await svc.get_storage_summary(tenant.id, ev.id)
            assert summary.total_items == 3
            assert summary.by_category == {"gin": 1, "vodka": 1, "mixer": 1}
            assert summary.total_line_value_eur == (
                Decimal("3833.16") + Decimal("390.04") + Decimal("864.13")
            )
            assert len(summary.rows) == 3
            cats = {r.category for r in summary.rows}
            assert cats == {"gin", "vodka", "mixer"}
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_storage_summary_empty_event():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        ev = await make_event(session, tenant.id)
        try:
            svc = EventStorageService(session)
            summary = await svc.get_storage_summary(tenant.id, ev.id)
            assert summary.total_items == 0
            assert summary.by_category == {}
            assert summary.total_line_value_eur is None
            assert summary.rows == []
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()
