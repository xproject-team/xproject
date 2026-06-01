"""Tests for GET /events/{event_id}/bar-category-totals (DASH.2).

Uses the isolated_client fixture so every test runs in a SAVEPOINT
that auto-rolls back. xproject_dev is never mutated.

Coverage:
  1. happy_path                         — 2 bars, 4 categories, rollup math
  2. null_category_fallback             — name-derived category works
  3. top_5_ranking                      — 7 products, only top 5 returned
  4. food_excluded_from_top_drinks      — food in buckets but not in top_5
  5. event_not_found_returns_404
  6. event_with_no_transactions         — empty bars list

Spec: dashboard redesign LOCKED May 27 2026.
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
from app.modules.events.models import Event, EventStatus
from app.modules.products.models import (
    Product, ProductCategory, ProductType, ProductUnit,
)
from app.modules.stock_transactions.models import (
    StockTransaction, TransactionSource,
)
from app.modules.venues.models import Venue


# ─── Helpers ─────────────────────────────────────────────────────────

async def _get_tenant(db: AsyncSession) -> Tenant:
    """Fetch the seeded Noma Group tenant from the test DB.

    The tenant exists in xproject_dev before any test starts.
    We read it through OUR transaction so subsequent inserts are linked.
    """
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
        scheduled_at=datetime(2026, 6, 19, 19, 0, tzinfo=timezone.utc),
        scheduled_end_at=datetime(2026, 6, 19, 23, 0, tzinfo=timezone.utc),
        status=EventStatus.DRAFT,
        expected_guest_count=1000,
        started_at=datetime.now(timezone.utc),
        version=1,
    )
    db.add(ev)
    await db.flush()
    return ev


async def _create_bar(
    db: AsyncSession, tenant_id: UUID, event_id: UUID, name: str,
) -> Bar:
    bar = Bar(
        tenant_id=tenant_id,
        event_id=event_id,
        name=name,
        bar_type="drinks",
        is_active=True,
    )
    db.add(bar)
    await db.flush()
    return bar


async def _create_product(
    db: AsyncSession,
    tenant_id: UUID,
    name: str,
    category: ProductCategory | None = None,
    product_type: ProductType = ProductType.DRINK,
) -> Product:
    """Create a product with a unique suffix to avoid colliding with
    the seeded xproject_dev catalog (constraint uq_products_tenant_
    name_type_active = UNIQUE(tenant_id, name, product_type)).

    The suffix is invisible to _classify_category() because the
    classifier does substring matching — 'Raffo-abc12345' still
    contains 'raffo' so the category fallback still works.
    """
    suffix = uuid4().hex[:8]
    p = Product(
        tenant_id=tenant_id,
        name=f"{name}-{suffix}",
        product_type=product_type,
        category=category,
        unit=ProductUnit.PIECE,
    )
    db.add(p)
    await db.flush()
    return p


async def _add_sale(
    db: AsyncSession,
    tenant_id: UUID,
    event_id: UUID,
    bar_id: UUID,
    product_id: UUID,
    qty: int,
    price_eur: float,
) -> None:
    """Insert one revenue-producing StockTransaction."""
    db.add(StockTransaction(
        tenant_id=tenant_id,
        event_id=event_id,
        bar_id=bar_id,
        product_id=product_id,
        qty=Decimal(str(qty)),
        deficit_qty=Decimal("0"),
        price_cents=int(price_eur * 100),
        source=TransactionSource.SLESH_POS,
        source_idempotency_key=f"test-{uuid4().hex}",
    ))


async def _login_in_isolation(client: AsyncClient) -> dict[str, str]:
    """Log in within the isolated client (override is active).

    The login hits /auth/login which reads users from the isolated
    session. Because the tenant + user already exist in xproject_dev
    and our session shares those tables (the SAVEPOINT is on top of
    the same data), the seeded omar@nomagroup.it credentials work.
    """
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": "omar@nomagroup.it", "password": "xproject2026"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, f"login failed: {r.text}"
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ─── 1. happy path ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_path_two_bars_four_categories(
    db_session: AsyncSession,
    isolated_client: AsyncClient,
):
    """Two bars sell drinks across the 4 display buckets → rollups correct."""
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    bar1 = await _create_bar(db_session, tenant.id, event.id, "Cocktail Bar")
    bar2 = await _create_bar(db_session, tenant.id, event.id, "Wine Bar")

    # Bar 1: 10 beer + 20 cocktails + 5 premium_cocktails
    beer    = await _create_product(db_session, tenant.id, "Raffo",
                                     ProductCategory.BEER_BOTTLE)
    cocktl  = await _create_product(db_session, tenant.id, "Sprtiz",
                                     ProductCategory.BASIC_COCKTAIL)
    premium = await _create_product(db_session, tenant.id, "Cocktail signature",
                                     ProductCategory.PREMIUM_COCKTAIL)
    await _add_sale(db_session, tenant.id, event.id, bar1.id, beer.id,    10, 6.0)
    await _add_sale(db_session, tenant.id, event.id, bar1.id, cocktl.id,  20, 10.0)
    await _add_sale(db_session, tenant.id, event.id, bar1.id, premium.id,  5, 15.0)

    # Bar 2: 8 wine
    wine = await _create_product(db_session, tenant.id, "Bottiglia Vino",
                                  ProductCategory.WINE_RED)
    await _add_sale(db_session, tenant.id, event.id, bar2.id, wine.id, 8, 8.0)

    await db_session.flush()
    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/bar-category-totals",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["event_id"] == str(event.id)
    assert len(data["bars"]) == 2

    by_name = {b["bar_name"]: b for b in data["bars"]}
    assert "Cocktail Bar" in by_name
    assert "Wine Bar" in by_name

    cb = by_name["Cocktail Bar"]
    buckets = {c["bucket"]: c for c in cb["categories"]}
    assert buckets["beer"]["units"] == 10
    assert Decimal(buckets["beer"]["revenue_eur"]) == Decimal("60.00")
    assert buckets["cocktails"]["units"] == 20
    assert buckets["premium_cocktails"]["units"] == 5
    assert cb["total_units"] == 35


# ─── 2. NULL-category fallback ──────────────────────────────────────

@pytest.mark.asyncio
async def test_null_category_falls_back_to_name_classifier(
    db_session: AsyncSession,
    isolated_client: AsyncClient,
):
    """A product with category=NULL but name='Raffo' lands in 'beer'."""
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id, "Bar X")

    # category=None → must fall back to _classify_category("Raffo") → beer
    p = await _create_product(db_session, tenant.id, "Raffo", category=None)
    await _add_sale(db_session, tenant.id, event.id, bar.id, p.id, 7, 5.0)

    await db_session.flush()
    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/bar-category-totals",
        headers=headers,
    )
    assert r.status_code == 200
    bars = r.json()["bars"]
    assert len(bars) == 1
    buckets = {c["bucket"]: c for c in bars[0]["categories"]}
    assert "beer" in buckets, f"expected beer bucket, got {list(buckets)}"
    assert buckets["beer"]["units"] == 7


# ─── 3. top-5 ranking ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_top_5_drinks_returns_only_five_sorted_by_units(
    db_session: AsyncSession,
    isolated_client: AsyncClient,
):
    """7 different drink products → top_5_drinks has exactly 5, descending."""
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id, "Bar Y")

    # Sales (units): 100, 90, 80, 70, 60, 50, 40 — top 5 should be 100..60
    quantities = [100, 90, 80, 70, 60, 50, 40]
    for i, q in enumerate(quantities):
        p = await _create_product(
            db_session, tenant.id, f"Drink-{i}", ProductCategory.BASIC_COCKTAIL,
        )
        await _add_sale(db_session, tenant.id, event.id, bar.id, p.id, q, 5.0)

    await db_session.flush()
    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/bar-category-totals",
        headers=headers,
    )
    assert r.status_code == 200
    top = r.json()["bars"][0]["top_5_drinks"]
    assert len(top) == 5
    units_descending = [d["units"] for d in top]
    assert units_descending == [100, 90, 80, 70, 60]


# ─── 4. food excluded from top drinks ───────────────────────────────

@pytest.mark.asyncio
async def test_food_in_buckets_but_excluded_from_top_drinks(
    db_session: AsyncSession,
    isolated_client: AsyncClient,
):
    """Burger sales appear in food bucket but NOT in top_5_drinks."""
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id, "Food Bar")

    # Big food sale + tiny drink sale
    burger = await _create_product(
        db_session, tenant.id, "Burger",
        category=None, product_type=ProductType.FOOD,
    )
    cocktail = await _create_product(
        db_session, tenant.id, "Sprtiz", ProductCategory.BASIC_COCKTAIL,
    )
    await _add_sale(db_session, tenant.id, event.id, bar.id, burger.id,   50, 8.0)
    await _add_sale(db_session, tenant.id, event.id, bar.id, cocktail.id,  3, 10.0)

    await db_session.flush()
    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/bar-category-totals",
        headers=headers,
    )
    assert r.status_code == 200
    bar_data = r.json()["bars"][0]
    buckets = {c["bucket"]: c for c in bar_data["categories"]}
    assert buckets["food"]["units"] == 50
    # Top-5 should contain only the cocktail, not the burger
    top_names = [d["product_name"] for d in bar_data["top_5_drinks"]]
    # Names have a uuid suffix per the test helper, so check by prefix.
    assert not any(n.startswith("Burger") for n in top_names)
    assert any(n.startswith("Sprtiz") for n in top_names)


# ─── 5. unknown event 404 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_event_returns_404(
    db_session: AsyncSession,
    isolated_client: AsyncClient,
):
    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{uuid4()}/bar-category-totals",
        headers=headers,
    )
    assert r.status_code == 404


# ─── 6. empty event (no transactions yet) ──────────────────────────

@pytest.mark.asyncio
async def test_event_with_no_transactions_returns_empty_bars(
    db_session: AsyncSession,
    isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)
    # No bars, no transactions.

    await db_session.flush()
    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{event.id}/bar-category-totals",
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["event_id"] == str(event.id)
    assert data["bars"] == []
