"""Tests for GET /warehouse/event/{event_id}/summary (T9).

Per-product roll-up of everything invoiced FOR a single event.

Uses the isolated_client + db_session fixtures so every test runs inside a
SAVEPOINT that auto-rolls back — xproject_dev is never mutated. We seed an
event + delivery_invoices + invoice_items through OUR transaction, then call
the endpoint through the same transaction (the isolated_client overrides
get_db with our session).

Coverage:
  1. empty event                  → rows=[], totals zero
  2. one invoice, two catalog     → two product rows, aggregation correct
  3. one miscellaneous item       → row with product_id=None
  4. same product across two      → rolls up into one row (SUM + COUNT)
     invoices for the event

Scope note: T9 returns invoiced_qty + invoiced_value_cents only. Dispatch
math (dispatched_qty / remaining_qty) is deferred to T10.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Tenant
from app.modules.events.models import Event, EventStatus
from app.modules.products.models import (
    Product, ProductCategory, ProductType, ProductUnit,
)
from app.modules.venues.models import Venue
from app.modules.warehouse.models import DeliveryInvoice, InvoiceItem


# ─── Helpers ─────────────────────────────────────────────────────────

async def _get_tenant(db: AsyncSession) -> Tenant:
    """Fetch the seeded Noma Group tenant (exists in xproject_dev)."""
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
) -> Event:
    ev = Event(
        tenant_id=tenant_id,
        venue_id=venue_id,
        name=f"Test Event {uuid4().hex[:8]}",
        scheduled_at=datetime(2026, 7, 1, 19, 0, tzinfo=timezone.utc),
        scheduled_end_at=datetime(2026, 7, 1, 23, 0, tzinfo=timezone.utc),
        status=EventStatus.DRAFT,
        expected_guest_count=1000,
        started_at=datetime.now(timezone.utc),
        version=1,
    )
    db.add(ev)
    await db.flush()
    return ev


async def _create_product(
    db: AsyncSession,
    tenant_id: UUID,
    name: str,
    category: ProductCategory | None = ProductCategory.BASIC_COCKTAIL,
    product_type: ProductType = ProductType.DRINK,
) -> Product:
    """Create a product with a unique suffix to dodge the
    uq_products_tenant_name_type_active constraint against seeded data.
    """
    suffix = uuid4().hex[:8]
    p = Product(
        tenant_id=tenant_id,
        name=f"{name}-{suffix}",
        product_type=product_type,
        category=category,
        unit=ProductUnit.BOTTLE,
    )
    db.add(p)
    await db.flush()
    return p


async def _create_invoice(
    db: AsyncSession, tenant_id: UUID, event_id: UUID,
) -> DeliveryInvoice:
    inv = DeliveryInvoice(
        tenant_id=tenant_id,
        event_id=event_id,
        supplier_name=f"Supplier {uuid4().hex[:6]}",
        expected_arrival_date=date(2026, 7, 1),
        status="EXPECTED",
    )
    db.add(inv)
    await db.flush()
    return inv


async def _add_catalog_item(
    db: AsyncSession,
    tenant_id: UUID,
    invoice_id: UUID,
    product_id: UUID,
    qty: str,
    line_total_cents: int | None,
) -> None:
    db.add(InvoiceItem(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        kind="catalog_product",
        product_id=product_id,
        expected_qty=Decimal(qty),
        line_total_cents=line_total_cents,
    ))


async def _add_misc_item(
    db: AsyncSession,
    tenant_id: UUID,
    invoice_id: UUID,
    description: str,
    qty: str,
    line_total_cents: int | None,
) -> None:
    db.add(InvoiceItem(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        kind="miscellaneous",
        miscellaneous_description=description,
        expected_qty=Decimal(qty),
        line_total_cents=line_total_cents,
    ))


async def _login_in_isolation(client: AsyncClient) -> dict[str, str]:
    """Log in within the isolated client (get_db override is active)."""
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": "omar@nomagroup.it", "password": "xproject2026"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, f"login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ─── 1. empty event ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_event_returns_no_rows_and_zero_totals(
    db_session: AsyncSession,
    isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    # No invoices.

    await db_session.flush()
    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/warehouse/event/{event.id}/summary",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["event_id"] == str(event.id)
    assert data["rows"] == []
    assert data["total_products"] == 0
    assert Decimal(data["total_qty"]) == Decimal("0")
    assert data["total_value_cents"] == 0


# ─── 2. one invoice, two catalog items ──────────────────────────────

@pytest.mark.asyncio
async def test_two_catalog_items_aggregate_correctly(
    db_session: AsyncSession,
    isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    invoice = await _create_invoice(db_session, tenant.id, event.id)

    gin = await _create_product(db_session, tenant.id, "Bombay Gin")
    rum = await _create_product(db_session, tenant.id, "Bacardi Rum")
    await _add_catalog_item(db_session, tenant.id, invoice.id, gin.id,
                            qty="12", line_total_cents=24000)
    await _add_catalog_item(db_session, tenant.id, invoice.id, rum.id,
                            qty="6", line_total_cents=9000)

    await db_session.flush()
    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/warehouse/event/{event.id}/summary",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["total_products"] == 2
    assert Decimal(data["total_qty"]) == Decimal("18")
    assert data["total_value_cents"] == 33000

    by_id = {row["product_id"]: row for row in data["rows"]}
    assert str(gin.id) in by_id
    assert str(rum.id) in by_id

    gin_row = by_id[str(gin.id)]
    assert gin_row["product_name"] == gin.name
    assert Decimal(gin_row["invoiced_qty"]) == Decimal("12")
    assert gin_row["invoiced_value_cents"] == 24000
    assert gin_row["unit_count"] == 1
    assert gin_row["product_type"] == "drink"
    assert gin_row["category"] == "basic_cocktail"

    rum_row = by_id[str(rum.id)]
    assert Decimal(rum_row["invoiced_qty"]) == Decimal("6")
    assert rum_row["invoiced_value_cents"] == 9000


# ─── 3. miscellaneous item ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_miscellaneous_item_has_null_product_id(
    db_session: AsyncSession,
    isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    invoice = await _create_invoice(db_session, tenant.id, event.id)

    await _add_misc_item(db_session, tenant.id, invoice.id,
                         description="Cleaning supplies",
                         qty="3", line_total_cents=1500)

    await db_session.flush()
    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/warehouse/event/{event.id}/summary",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["total_products"] == 1
    row = data["rows"][0]
    assert row["product_id"] is None
    assert row["product_name"] == "Cleaning supplies"
    assert row["category"] is None
    assert row["product_type"] is None
    assert Decimal(row["invoiced_qty"]) == Decimal("3")
    assert row["invoiced_value_cents"] == 1500
    assert row["unit_count"] == 1


# ─── 4. same product across two invoices rolls up ───────────────────

@pytest.mark.asyncio
async def test_same_product_across_two_invoices_rolls_up(
    db_session: AsyncSession,
    isolated_client: AsyncClient,
):
    """Two invoices for the same event, both with the same product, collapse
    into one row whose qty/value are summed and unit_count is 2. Also proves
    a NULL line_total is treated as 0.
    """
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    inv_a = await _create_invoice(db_session, tenant.id, event.id)
    inv_b = await _create_invoice(db_session, tenant.id, event.id)

    vodka = await _create_product(db_session, tenant.id, "Absolut Vodka")
    await _add_catalog_item(db_session, tenant.id, inv_a.id, vodka.id,
                            qty="10", line_total_cents=20000)
    await _add_catalog_item(db_session, tenant.id, inv_b.id, vodka.id,
                            qty="4", line_total_cents=None)  # NULL → 0

    await db_session.flush()
    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/warehouse/event/{event.id}/summary",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["total_products"] == 1
    row = data["rows"][0]
    assert row["product_id"] == str(vodka.id)
    assert Decimal(row["invoiced_qty"]) == Decimal("14")
    assert row["invoiced_value_cents"] == 20000  # 20000 + 0
    assert row["unit_count"] == 2
