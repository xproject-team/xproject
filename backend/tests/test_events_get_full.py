"""Tests for GET /events/{event_id}/full — wizard edit-mode preload (T12/Chunk 1).

Returns an event in the SAME index-referenced shape POST/PUT /events/full
accept, so the wizard can GET → populate → edit → PUT round-trip.

Uses the isolated_client + db_session SAVEPOINT fixtures — every test runs in
a transaction that auto-rolls back, so xproject_dev is never mutated. The
round-trip is exercised over HTTP/JSON on purpose: JSON serialization +
index references are part of the contract this endpoint must uphold.

Coverage:
  1. happy path            — counts + in-bounds indices
  2. empty event           — all arrays []
  3. not found             — 404 event_not_found
  4. tenant isolation      — cross-tenant read is 404 (not 403)
  5. deterministic order   — bars created_at ASC, products name ASC; stable
  6. round trip via PUT    — GET → PUT → GET is identical (the index contract)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Tenant
from app.modules.events.models import Event, EventStatus
from app.modules.venues.models import Venue

_NOW = datetime(2026, 7, 1, 18, 0, tzinfo=timezone.utc)


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


async def _login_in_isolation(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": "omar@nomagroup.it", "password": "xproject2026"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, f"login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _event_field(venue_id: UUID, name: str | None = None) -> dict:
    return {
        "name": name or f"full-{uuid4().hex[:8]}",
        "venue_id": str(venue_id),
        "scheduled_at": _NOW.isoformat(),
        "scheduled_end_at": (_NOW + timedelta(hours=8)).isoformat(),
        "expected_guest_count": 1000,
    }


def _product(name: str, category: str = "basic_cocktail") -> dict:
    return {
        "name": name,
        "product_type": "drink",
        "category": category,
        "unit": "bottle",
        "default_price_cents": 1200,
        "iva_pct": 0.1,
    }


async def _post_full(client, headers, payload: dict) -> dict:
    r = await client.post("/api/v1/events/full", json=payload, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ─── 1. happy path ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_full_happy_path(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    await db_session.flush()
    headers = await _login_in_isolation(isolated_client)

    suffix = uuid4().hex[:8]
    payload = {
        "event": _event_field(venue.id),
        "bars": [{"name": "Main Bar"}, {"name": "Beer Bar"}],
        "products": [
            _product(f"Gin-{suffix}"),
            _product(f"Vodka-{suffix}"),
            _product(f"Rum-{suffix}"),
        ],
        "menu": [
            {"bar_index": 0, "product_index": 0, "price_cents": 1200},
            {"bar_index": 0, "product_index": 1, "price_cents": 1200},
            {"bar_index": 1, "product_index": 2, "price_cents": 1000},
            {"bar_index": 0, "product_index": 2, "price_cents": 1100},
        ],
        "allocations": [
            {"bar_index": 0, "product_index": 0, "qty": 24},
            {"bar_index": 0, "product_index": 1, "qty": 12},
            {"bar_index": 1, "product_index": 2, "qty": 6},
            {"bar_index": 0, "product_index": 2, "qty": 8},
        ],
    }
    created = await _post_full(isolated_client, headers, payload)
    event_id = created["event"]["id"]

    r = await isolated_client.get(
        f"/api/v1/events/{event_id}/full", headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["event"]["id"] == event_id
    assert len(data["bars"]) == 2
    assert len(data["products"]) == 3
    assert len(data["menu"]) == 4
    assert len(data["allocations"]) == 4

    n_bars, n_products = len(data["bars"]), len(data["products"])
    for row in data["menu"] + data["allocations"]:
        assert 0 <= row["bar_index"] < n_bars
        assert 0 <= row["product_index"] < n_products


# ─── 2. empty event ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_full_empty_event(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    await db_session.flush()
    headers = await _login_in_isolation(isolated_client)

    created = await _post_full(
        isolated_client, headers, {"event": _event_field(venue.id)},
    )
    event_id = created["event"]["id"]

    r = await isolated_client.get(
        f"/api/v1/events/{event_id}/full", headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["event"]["id"] == event_id
    assert data["bars"] == []
    assert data["products"] == []
    assert data["menu"] == []
    assert data["allocations"] == []


# ─── 3. not found ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_full_not_found(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{uuid4()}/full", headers=headers,
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error"] == "event_not_found"


# ─── 4. tenant isolation ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_full_tenant_isolation(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    """An event in tenant B is invisible to tenant A → 404 (not 403)."""
    # Tenant B, fully inside our SAVEPOINT.
    tenant_b = Tenant(name="Other Co", slug=f"other-{uuid4().hex[:10]}")
    db_session.add(tenant_b)
    await db_session.flush()
    venue_b = await _create_venue(db_session, tenant_b.id)
    event_b = Event(
        tenant_id=tenant_b.id,
        venue_id=venue_b.id,
        name="Tenant B event",
        scheduled_at=_NOW,
        scheduled_end_at=_NOW + timedelta(hours=8),
        status=EventStatus.DRAFT,
        expected_guest_count=500,
        version=1,
    )
    db_session.add(event_b)
    await db_session.flush()

    # Authenticated as tenant A (omar / noma-group).
    headers = await _login_in_isolation(isolated_client)
    r = await isolated_client.get(
        f"/api/v1/events/{event_b.id}/full", headers=headers,
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error"] == "event_not_found"


# ─── 5. deterministic ordering ──────────────────────────────────────

@pytest.mark.asyncio
async def test_get_full_deterministic_ordering(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    """bars = created_at ASC (Zebra was created first → first),
    products = name ASC (Aardvark before Zebra). Stable across calls.
    """
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    await db_session.flush()
    headers = await _login_in_isolation(isolated_client)

    suffix = uuid4().hex[:8]
    payload = {
        "event": _event_field(venue.id),
        # Bars in NON-alphabetical creation order.
        "bars": [{"name": "Zebra Bar"}, {"name": "Aardvark Bar"}],
        # Products in NON-alphabetical creation order.
        "products": [
            _product(f"Zebra-{suffix}"),
            _product(f"Aardvark-{suffix}"),
        ],
        "menu": [
            {"bar_index": 0, "product_index": 0, "price_cents": 1000},
            {"bar_index": 1, "product_index": 1, "price_cents": 1000},
        ],
        "allocations": [
            {"bar_index": 0, "product_index": 0, "qty": 5},
        ],
    }
    created = await _post_full(isolated_client, headers, payload)
    event_id = created["event"]["id"]

    r1 = await isolated_client.get(
        f"/api/v1/events/{event_id}/full", headers=headers,
    )
    r2 = await isolated_client.get(
        f"/api/v1/events/{event_id}/full", headers=headers,
    )
    assert r1.status_code == 200 and r2.status_code == 200
    d1, d2 = r1.json(), r2.json()

    # bars: created_at ASC → Zebra (created first) first. Stable.
    assert [b["name"] for b in d1["bars"]] == ["Zebra Bar", "Aardvark Bar"]
    assert [b["name"] for b in d1["bars"]] == [b["name"] for b in d2["bars"]]

    # products: name ASC → Aardvark first. Stable.
    assert d1["products"][0]["name"].startswith("Aardvark")
    assert d1["products"][1]["name"].startswith("Zebra")
    assert [p["name"] for p in d1["products"]] == [
        p["name"] for p in d2["products"]
    ]

    # The menu index that pointed at "Zebra" product (creation index 0) must
    # now resolve to product_index 1 (Zebra sorts last by name).
    zebra_menu = next(
        m for m in d1["menu"]
        if d1["products"][m["product_index"]]["name"].startswith("Zebra")
    )
    assert zebra_menu["bar_index"] == 0  # Zebra Bar is bars[0]


# ─── 6. round trip via PUT (validates the whole index contract) ─────

@pytest.mark.asyncio
async def test_get_full_round_trip_via_put(
    db_session: AsyncSession, isolated_client: AsyncClient,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    await db_session.flush()
    headers = await _login_in_isolation(isolated_client)

    suffix = uuid4().hex[:8]
    payload = {
        "event": _event_field(venue.id),
        "bars": [{"name": "Bar A"}, {"name": "Bar B"}],
        "products": [
            _product(f"Gin-{suffix}"),
            _product(f"Vodka-{suffix}"),
            _product(f"Rum-{suffix}"),
        ],
        "menu": [
            {"bar_index": 0, "product_index": 0, "price_cents": 1200},
            {"bar_index": 1, "product_index": 1, "price_cents": 1000},
            {"bar_index": 0, "product_index": 2, "price_cents": 1100},
        ],
        "allocations": [
            {"bar_index": 0, "product_index": 0, "qty": 24},
            {"bar_index": 1, "product_index": 1, "qty": 12},
        ],
    }
    created = await _post_full(isolated_client, headers, payload)
    event_id = created["event"]["id"]

    # GET #1
    g1 = (await isolated_client.get(
        f"/api/v1/events/{event_id}/full", headers=headers,
    )).json()

    # Transform GET response → FullEventCreate shape (event: EventResponse →
    # EventCreate; venue object → venue_id; arrays pass through unchanged).
    ev = g1["event"]
    put_payload = {
        "event": {
            "name": ev["name"],
            "venue_id": ev["venue"]["id"],
            "scheduled_at": ev["scheduled_at"],
            "scheduled_end_at": ev["scheduled_end_at"],
            "expected_guest_count": ev["expected_guest_count"],
            "stripe_ragione_sociale": ev["stripe_ragione_sociale"],
            "staff_arrival_time": ev["staff_arrival_time"],
            "wristband_qty_per_type": ev["wristband_qty_per_type"],
            "topup_denominations_user": ev["topup_denominations_user"],
            "topup_denominations_staff": ev["topup_denominations_staff"],
            "refund_min_credit_cents": ev["refund_min_credit_cents"],
            "refund_fee_cents": ev["refund_fee_cents"],
            "refund_window_open_at": ev["refund_window_open_at"],
            "refund_window_close_at": ev["refund_window_close_at"],
            "food_revenue_share_pct": ev["food_revenue_share_pct"],
        },
        "bars": g1["bars"],
        "products": g1["products"],
        "menu": g1["menu"],
        "allocations": g1["allocations"],
    }

    put_resp = await isolated_client.put(
        f"/api/v1/events/{event_id}/full", json=put_payload, headers=headers,
    )
    assert put_resp.status_code == 200, put_resp.text

    # GET #2 — must be identical in every composite section.
    g2 = (await isolated_client.get(
        f"/api/v1/events/{event_id}/full", headers=headers,
    )).json()

    assert g2["event"]["id"] == g1["event"]["id"]
    assert g2["bars"] == g1["bars"]
    assert g2["products"] == g1["products"]
    assert g2["menu"] == g1["menu"]
    assert g2["allocations"] == g1["allocations"]
