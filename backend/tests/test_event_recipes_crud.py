"""Tests for /api/v1/event-recipes CRUD (Chunk 2 part 1).

Uses the isolated_client + db_session fixtures so every test runs inside
a SAVEPOINT that auto-rolls back — xproject_dev is never mutated. See
tests/test_event_warehouse_summary.py for the pattern this file follows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Tenant
from app.modules.bars.models import Bar
from app.modules.event_storage.models import EventCategoryIngredient, SupplierProduct
from app.modules.events.models import Event, EventStatus
from app.modules.products.models import Product, ProductCategory, ProductType, ProductUnit
from app.modules.venues.models import Venue


# ─── Helpers ─────────────────────────────────────────────────────────

async def _get_tenant(db: AsyncSession) -> Tenant:
    r = await db.execute(select(Tenant).where(Tenant.slug == "noma-group"))
    return r.scalar_one()


async def _create_venue(db: AsyncSession, tenant_id: UUID) -> Venue:
    v = Venue(
        tenant_id=tenant_id,
        name=f"Test Venue {uuid4().hex[:8]}",
        address="Test address",
    )
    db.add(v)
    await db.flush()
    return v


async def _create_event(
    db: AsyncSession, tenant_id: UUID, venue_id: UUID,
    status: EventStatus = EventStatus.DRAFT,
) -> Event:
    ev = Event(
        tenant_id=tenant_id,
        venue_id=venue_id,
        name=f"Test Event {uuid4().hex[:8]}",
        scheduled_at=datetime(2026, 7, 1, 19, 0, tzinfo=timezone.utc),
        scheduled_end_at=datetime(2026, 7, 1, 23, 0, tzinfo=timezone.utc),
        status=status,
        expected_guest_count=1000,
        version=1,
    )
    db.add(ev)
    await db.flush()
    return ev


async def _create_bar(
    db: AsyncSession, tenant_id: UUID, event_id: UUID, name: str = "Main Bar",
) -> Bar:
    bar = Bar(
        tenant_id=tenant_id,
        event_id=event_id,
        name=f"{name}-{uuid4().hex[:6]}",
        bar_type="drinks",
        is_active=True,
    )
    db.add(bar)
    await db.flush()
    return bar


async def _create_supplier_product(
    db: AsyncSession, tenant_id: UUID, item_name: str = "Test Gin",
) -> SupplierProduct:
    sp = SupplierProduct(
        tenant_id=tenant_id,
        supplier_name="Partesa",
        supplier_sku=f"SKU-{uuid4().hex[:8]}",
        item_name=item_name,
        category="gin",
        default_unit="BO",
        units_per_pack=1,
    )
    db.add(sp)
    await db.flush()
    return sp


async def _create_product(
    db: AsyncSession, tenant_id: UUID, name: str,
) -> Product:
    p = Product(
        tenant_id=tenant_id,
        name=name,
        product_type=ProductType.DRINK,
        category=ProductCategory.BASIC_COCKTAIL,
        unit=ProductUnit.GLASS,
        default_price_cents=1000,
        is_archived=False,
    )
    db.add(p)
    await db.flush()
    return p


async def _login_in_isolation(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": "omar@nomagroup.it", "password": "xproject2026"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, f"login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ─── create: happy path ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_row_happy_path(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id)
    sp = await _create_supplier_product(db_session, tenant.id)
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.post(
        "/api/v1/event-recipes",
        json={
            "event_id": str(event.id),
            "drink_name": "GIN TONIC",
            "bar_id": str(bar.id),
            "supplier_product_id": str(sp.id),
            "ml_per_sale": 45.0,
            "is_optional": False,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["drink_name"] == "GIN TONIC"
    assert data["bar_id"] == str(bar.id)
    assert data["bar_name"] == bar.name
    assert data["supplier_product_id"] == str(sp.id)
    assert data["supplier_product_name"] == sp.item_name
    assert data["ml_per_sale"] == 45.0
    assert data["is_optional"] is False


# ─── create: event not DRAFT ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_row_event_not_draft(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id, status=EventStatus.COMPLETED)
    bar = await _create_bar(db_session, tenant.id, event.id)
    sp = await _create_supplier_product(db_session, tenant.id)
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.post(
        "/api/v1/event-recipes",
        json={
            "event_id": str(event.id),
            "drink_name": "GIN TONIC",
            "bar_id": str(bar.id),
            "supplier_product_id": str(sp.id),
            "ml_per_sale": 45.0,
        },
        headers=headers,
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "event_not_draft"


# ─── create: duplicate ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_row_duplicate(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id)
    sp = await _create_supplier_product(db_session, tenant.id)
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    body = {
        "event_id": str(event.id),
        "drink_name": "GIN TONIC",
        "bar_id": str(bar.id),
        "supplier_product_id": str(sp.id),
        "ml_per_sale": 45.0,
    }
    r1 = await isolated_client.post("/api/v1/event-recipes", json=body, headers=headers)
    assert r1.status_code == 201, r1.text

    r2 = await isolated_client.post("/api/v1/event-recipes", json=body, headers=headers)
    assert r2.status_code == 422, r2.text
    assert r2.json()["detail"]["error"] == "row_exists"


# ─── patch: ml_per_sale ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_ml_per_sale(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id)
    sp = await _create_supplier_product(db_session, tenant.id)
    row = EventCategoryIngredient(
        tenant_id=tenant.id, event_id=event.id, slesh_category="SPRITZ",
        supplier_product_id=sp.id, bar_id=bar.id, ml_per_sale=Decimal("40.00"),
    )
    db_session.add(row)
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.patch(
        f"/api/v1/event-recipes/{row.id}",
        json={"ml_per_sale": 50.0, "is_optional": True},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ml_per_sale"] == 50.0
    assert data["is_optional"] is True


# ─── patch: event not DRAFT ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_not_draft(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id, status=EventStatus.COMPLETED)
    bar = await _create_bar(db_session, tenant.id, event.id)
    sp = await _create_supplier_product(db_session, tenant.id)
    row = EventCategoryIngredient(
        tenant_id=tenant.id, event_id=event.id, slesh_category="SPRITZ",
        supplier_product_id=sp.id, bar_id=bar.id, ml_per_sale=Decimal("40.00"),
    )
    db_session.add(row)
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.patch(
        f"/api/v1/event-recipes/{row.id}",
        json={"ml_per_sale": 50.0},
        headers=headers,
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "event_not_draft"


# ─── delete ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_row(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id)
    sp = await _create_supplier_product(db_session, tenant.id)
    row = EventCategoryIngredient(
        tenant_id=tenant.id, event_id=event.id, slesh_category="SPRITZ",
        supplier_product_id=sp.id, bar_id=bar.id, ml_per_sale=Decimal("40.00"),
    )
    db_session.add(row)
    await db_session.flush()
    row_id = row.id

    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.delete(f"/api/v1/event-recipes/{row_id}", headers=headers)
    assert r.status_code == 204, r.text

    check = await db_session.execute(
        select(EventCategoryIngredient).where(EventCategoryIngredient.id == row_id)
    )
    assert check.scalar_one_or_none() is None


# ─── bulk: atomic (one bad row rejects the whole batch) ──────────────

@pytest.mark.asyncio
async def test_bulk_create_atomic(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id)
    sps = [await _create_supplier_product(db_session, tenant.id, f"Item {i}") for i in range(10)]
    for i in range(9):
        await _create_product(db_session, tenant.id, f"DRINK {i}")
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)

    good_rows = [
        {
            "event_id": str(event.id),
            "drink_name": f"DRINK {i}",
            "bar_id": str(bar.id),
            "supplier_product_id": str(sps[i].id),
            "ml_per_sale": 45.0,
        }
        for i in range(9)
    ]
    bad_row = {
        "event_id": str(event.id),
        "drink_name": "BAD DRINK",
        "bar_id": str(uuid4()),  # unknown bar -> invalid
        "supplier_product_id": str(sps[9].id),
        "ml_per_sale": 45.0,
    }
    rows = good_rows + [bad_row]

    r = await isolated_client.post(
        "/api/v1/event-recipes/bulk",
        json={"event_id": str(event.id), "rows": rows},
        headers=headers,
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "event_recipes_bulk_validation_failed"
    assert len(r.json()["detail"]["items"]) == 1
    assert r.json()["detail"]["items"][0]["index"] == 9

    # Nothing was inserted — whole batch rejected.
    check = await db_session.execute(
        select(EventCategoryIngredient).where(EventCategoryIngredient.event_id == event.id)
    )
    assert check.scalars().all() == []

    # Now post just the 9 good rows — succeeds atomically.
    r2 = await isolated_client.post(
        "/api/v1/event-recipes/bulk",
        json={"event_id": str(event.id), "rows": good_rows},
        headers=headers,
    )
    assert r2.status_code == 201, r2.text
    assert len(r2.json()) == 9


# ─── list: denormalized names ────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_by_event_returns_denormalized_names(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id, name="NO.3 BAR")
    sp = await _create_supplier_product(db_session, tenant.id, item_name="GIN No 3")
    row = EventCategoryIngredient(
        tenant_id=tenant.id, event_id=event.id, slesh_category="GIN TONIC",
        supplier_product_id=sp.id, bar_id=bar.id, ml_per_sale=Decimal("45.00"),
    )
    db_session.add(row)
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(f"/api/v1/event-recipes/{event.id}", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["read_only"] is False
    assert len(data["rows"]) == 1
    row_data = data["rows"][0]
    assert row_data["drink_name"] == "GIN TONIC"
    assert row_data["bar_name"] == bar.name
    assert row_data["supplier_product_name"] == "GIN No 3"


# ─── list: LIVE event returns read_only ──────────────────────────────

@pytest.mark.asyncio
async def test_list_by_event_on_live_event_is_read_only(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id, status=EventStatus.COMPLETED)
    bar = await _create_bar(db_session, tenant.id, event.id)
    sp = await _create_supplier_product(db_session, tenant.id)
    row = EventCategoryIngredient(
        tenant_id=tenant.id, event_id=event.id, slesh_category="SPRITZ",
        supplier_product_id=sp.id, bar_id=bar.id, ml_per_sale=Decimal("40.00"),
    )
    db_session.add(row)
    await db_session.flush()

    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(f"/api/v1/event-recipes/{event.id}", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["read_only"] is True
    assert len(data["rows"]) == 1
