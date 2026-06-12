"""HTTP-level tests for the event_storage router. Uses the Owner login
from conftest (Noma tenant) and creates/cleans up isolated test data
under that tenant for each test.

Each test seeds its own supplier_products (uuid-suffixed SKUs to avoid
collisions across parallel runs) and event, then exercises the endpoint
and tears down via direct DB calls in a finally block.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.modules.event_storage.models import EventStockItem, SupplierProduct
from app.modules.events.models import EventStatus
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_event,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio

API = "/api/v1/event-storage"


# ─── Cleanup helpers (owner_token is for Noma tenant, so we must purge
#                      our test rows after each test) ────────────────

async def _cleanup_test_data(supplier_skus: list[str], event_id: UUID | None = None) -> None:
    """Remove supplier_products by SKU + any event_stock_items they
    reference. Runs after each test as the Noma tenant is shared."""
    async with TestSessionLocal() as session:
        sps = (await session.execute(
            select(SupplierProduct).where(
                SupplierProduct.supplier_sku.in_(supplier_skus),
            )
        )).scalars().all()
        if sps:
            sp_ids = [sp.id for sp in sps]
            await session.execute(
                delete(EventStockItem).where(
                    EventStockItem.supplier_product_id.in_(sp_ids),
                )
            )
            await session.execute(
                delete(SupplierProduct).where(
                    SupplierProduct.id.in_(sp_ids),
                )
            )
        await session.commit()


# ─── supplier-products endpoints ─────────────────────────────────────

async def test_create_supplier_product_201(
    client: AsyncClient, owner_headers: dict[str, str],
):
    sku = f"TEST-{uuid4().hex[:8]}"
    try:
        resp = await client.post(
            f"{API}/supplier-products",
            headers=owner_headers,
            json={
                "supplier_name": "Partesa",
                "supplier_sku": sku,
                "item_name": "Test Gin 1L",
                "category": "gin",
                "default_unit": "BO",
                "units_per_pack": 1,
                "volume_per_unit_ml": 1000,
                "last_unit_price_eur": "26.20",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["supplier_sku"] == sku
        assert body["category"] == "gin"
        assert body["default_unit"] == "BO"
        assert Decimal(body["last_unit_price_eur"]) == Decimal("26.20")
    finally:
        await _cleanup_test_data([sku])


async def test_create_supplier_product_idempotent_refreshes_price(
    client: AsyncClient, owner_headers: dict[str, str],
):
    sku = f"TEST-{uuid4().hex[:8]}"
    payload = {
        "supplier_name": "Partesa",
        "supplier_sku": sku,
        "item_name": "Test Item",
        "category": "vodka",
        "default_unit": "BO",
        "units_per_pack": 1,
        "last_unit_price_eur": "19.10",
    }
    try:
        r1 = await client.post(f"{API}/supplier-products", headers=owner_headers, json=payload)
        assert r1.status_code == 201
        id1 = r1.json()["id"]

        payload["last_unit_price_eur"] = "21.00"
        r2 = await client.post(f"{API}/supplier-products", headers=owner_headers, json=payload)
        assert r2.status_code == 201
        body = r2.json()
        assert body["id"] == id1, "must be same row (idempotent)"
        assert Decimal(body["last_unit_price_eur"]) == Decimal("21.00")
    finally:
        await _cleanup_test_data([sku])


async def test_list_supplier_products_filter_by_category(
    client: AsyncClient, owner_headers: dict[str, str],
):
    sku_gin = f"TGIN-{uuid4().hex[:8]}"
    sku_vodka = f"TVKA-{uuid4().hex[:8]}"
    try:
        await client.post(f"{API}/supplier-products", headers=owner_headers, json={
            "supplier_sku": sku_gin, "item_name": "Test Gin",
            "category": "gin", "default_unit": "BO",
        })
        await client.post(f"{API}/supplier-products", headers=owner_headers, json={
            "supplier_sku": sku_vodka, "item_name": "Test Vodka",
            "category": "vodka", "default_unit": "BO",
        })
        resp = await client.get(
            f"{API}/supplier-products?category=gin",
            headers=owner_headers,
        )
        assert resp.status_code == 200
        skus = {row["supplier_sku"] for row in resp.json()}
        assert sku_gin in skus
        assert sku_vodka not in skus
    finally:
        await _cleanup_test_data([sku_gin, sku_vodka])


# ─── items endpoints ────────────────────────────────────────────────

async def test_bulk_upsert_roundtrip_list_and_summary(
    client: AsyncClient, owner_headers: dict[str, str],
):
    """End-to-end: create supplier_product, declare an event_stock_item
    via bulk endpoint, list it back, get summary, then clean up."""
    sku = f"TBE-{uuid4().hex[:8]}"
    tenant_id_for_test = None
    event_id = None
    sp_id = None
    try:
        # Need a real event in Noma tenant — create via TestSessionLocal
        # but we don't know the Noma tenant id from outside, so log in
        # to get current user and use that tenant.
        # Simpler: create supplier_product via API (we have owner_headers),
        # then derive tenant_id from the response.
        r_sp = await client.post(
            f"{API}/supplier-products", headers=owner_headers,
            json={
                "supplier_sku": sku, "item_name": "Test Item",
                "category": "gin", "default_unit": "BO",
            },
        )
        assert r_sp.status_code == 201
        sp_id = r_sp.json()["id"]
        tenant_id_for_test = UUID(r_sp.json()["tenant_id"])

        async with TestSessionLocal() as s:
            ev = await make_event(s, tenant_id_for_test, status=EventStatus.DRAFT)
            await s.commit()
            event_id = ev.id

        # Bulk upsert
        r_bulk = await client.post(
            f"{API}/items/bulk?event_id={event_id}",
            headers=owner_headers,
            json={"items": [{
                "supplier_product_id": sp_id,
                "qty_received": "240",
                "unit": "BO",
                "unit_price_eur": "26.20",
                "line_total_eur": "3833.16",
            }]},
        )
        assert r_bulk.status_code == 200, r_bulk.text
        assert len(r_bulk.json()) == 1

        # List
        r_list = await client.get(
            f"{API}/items?event_id={event_id}", headers=owner_headers,
        )
        assert r_list.status_code == 200
        rows = r_list.json()
        assert len(rows) == 1
        assert Decimal(rows[0]["qty_received"]) == Decimal("240")

        # Summary
        r_sum = await client.get(
            f"{API}/summary?event_id={event_id}", headers=owner_headers,
        )
        assert r_sum.status_code == 200
        summary = r_sum.json()
        assert summary["total_items"] == 1
        assert summary["by_category"] == {"gin": 1}
        assert Decimal(summary["total_line_value_eur"]) == Decimal("3833.16")
    finally:
        # Drop stock items + event before supplier_product (FK RESTRICT)
        if event_id is not None:
            async with TestSessionLocal() as s:
                await s.execute(
                    delete(EventStockItem).where(
                        EventStockItem.event_id == event_id,
                    )
                )
                from app.modules.events.models import Event as _Event
                await s.execute(
                    delete(_Event).where(_Event.id == event_id),
                )
                await s.commit()
        await _cleanup_test_data([sku])


async def test_bulk_upsert_404_on_missing_event(
    client: AsyncClient, owner_headers: dict[str, str],
):
    resp = await client.post(
        f"{API}/items/bulk?event_id={uuid4()}",
        headers=owner_headers,
        json={"items": []},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "event_not_found"


async def test_bulk_upsert_400_on_unknown_supplier_product(
    client: AsyncClient, owner_headers: dict[str, str],
):
    sku = f"TBAD-{uuid4().hex[:8]}"
    event_id = None
    try:
        # Create a real event so we get past the 404 path
        r_sp = await client.post(
            f"{API}/supplier-products", headers=owner_headers,
            json={
                "supplier_sku": sku, "item_name": "Tmp",
                "category": "gin", "default_unit": "BO",
            },
        )
        tenant_id = UUID(r_sp.json()["tenant_id"])
        async with TestSessionLocal() as s:
            ev = await make_event(s, tenant_id, status=EventStatus.DRAFT)
            await s.commit()
            event_id = ev.id

        # Bulk with a bogus supplier_product_id
        resp = await client.post(
            f"{API}/items/bulk?event_id={event_id}",
            headers=owner_headers,
            json={"items": [{
                "supplier_product_id": str(uuid4()),
                "qty_received": "10",
                "unit": "BO",
            }]},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "supplier_product_not_found"
    finally:
        if event_id is not None:
            async with TestSessionLocal() as s:
                from app.modules.events.models import Event as _Event
                await s.execute(delete(_Event).where(_Event.id == event_id))
                await s.commit()
        await _cleanup_test_data([sku])


async def test_list_items_404_on_missing_event(
    client: AsyncClient, owner_headers: dict[str, str],
):
    resp = await client.get(
        f"{API}/items?event_id={uuid4()}", headers=owner_headers,
    )
    assert resp.status_code == 404


async def test_summary_404_on_missing_event(
    client: AsyncClient, owner_headers: dict[str, str],
):
    resp = await client.get(
        f"{API}/summary?event_id={uuid4()}", headers=owner_headers,
    )
    assert resp.status_code == 404


async def test_delete_item_404(
    client: AsyncClient, owner_headers: dict[str, str],
):
    resp = await client.delete(
        f"{API}/items/{uuid4()}", headers=owner_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "event_stock_item_not_found"


# ─── Auth required ──────────────────────────────────────────────────

async def test_endpoints_require_auth(client: AsyncClient):
    """No Authorization header -> 401 across the board."""
    resp = await client.get(f"{API}/supplier-products")
    assert resp.status_code == 401
