#!/usr/bin/env python3
"""create_sundance_15_draft.py — one-off script to create a Sundance 15
DRAFT event via POST /api/v1/events/full, so end-to-end readiness
testing (recipes -> charge bars -> go live -> Slesh sync -> depletion
-> alerts) can start immediately without walking the wizard by hand.

THROWAWAY TEST UTILITY. Not imported by the app, not covered by CI.
Kept in backend/scripts/ so the exact payload is reproducible.

Idempotent: if a "Sundance 15" DRAFT already exists, prints its id and
exits without creating anything. Safe to re-run.

Usage:
    venv/bin/python backend/scripts/create_sundance_15_draft.py
Requires the API server running locally (default http://localhost:8000).

─── Where this data came from ──────────────────────────────────────────

The task's brief pointed at "Sundance 14 SIMULATION"
(5cc1e702-be0a-4880-b429-fb4129989dc4) as the source to copy bars/
products/menu from. Inspecting it directly showed:
  - 0 rows in event_products (no menu at all)
  - slesh_negozio_id NULL on every bar

Copying that event verbatim would produce a Sundance 15 draft with an
EMPTY menu, which fails this script's own verification checklist
(event_products count expected > 0, ~28). So bars/products/menu were
instead copied from "Sundance 14" (81cc702b-43af-4c50-87db-
d04d93592218, status DRAFT) — the actual fully-configured reference
event, with 29 distinct products and a real menu. See the report for
the full explanation; this is flagged prominently, not a silent
substitution.

Two "TOTALE DISPOSITIVI" / "Accrediti ingresso" rows on 81cc702b were
NOT replicated — they look like Excel-import artifacts (a device-count
total row and a near-duplicate of the "Recharge" bar), not real
operational bars. A single clean "Recharge" bar (bar_type=recharge)
was used instead, matching the wizard's own seeding convention.

slesh_negozio_id is NULL on every bar here, by design. Neither
Sundance 14 event has a real Slesh shop linkage. The only bars with
ANY slesh_negozio_id are on a COMPLETED simulation instance
(f786da33-6bfc-4e0d-bfac-799393182ce1), and those values
("sim-cassa-d9d8" etc.) are synthetic placeholders generated for the
depletion-math test harness — not real Slesh shop ids. Copying them
into Sundance 15 would create a false impression that Slesh linkage is
done. Real linkage must happen via the SleshShopPicker (Bars step of
the wizard, or the Bars edit page) before Go-Live.
"""
from __future__ import annotations

import sys

import httpx

API_BASE = "http://localhost:8000/api/v1"
OMAR_EMAIL = "omar@nomagroup.it"
OMAR_PASSWORD = "xproject2026"

EVENT_NAME = "Sundance 15"
VENUE_NAME = "Villa Alberico Roma"
# Address + capacity copied from the existing "Villa Alberico" venue
# (f50b85ba-3065-4ece-8431-d0123f5b188c) used by every Sundance 14
# event — same physical venue, just named per the task's brief
# ("Villa Alberico Roma", distinct from the existing "Villa Alberico"
# and "Villa Alberico Test" venue rows). Flagged in the report.
VENUE_ADDRESS = "Via di Fioranello 18, 00178 Roma"
VENUE_CAPACITY = 1600

# Event starts 6pm per the brief; end time isn't specified, so this
# copies Sundance 14 DRAFT's actual duration (10 hours, evening into
# early morning) rather than guessing a round number.
SCHEDULED_AT = "2026-07-05T18:00:00+02:00"
SCHEDULED_END_AT = "2026-07-06T04:00:00+02:00"
EXPECTED_GUEST_COUNT = 1600
FOOD_REVENUE_SHARE_PCT = 30  # matches Sundance 14 DRAFT

# ─── Bars — copied from "Sundance 14" DRAFT (81cc702b) ──────────────────
BARS = [
    {"name": "CASSA",       "bar_type": "service",  "device_count": 4},
    {"name": "MAIN BAR",    "bar_type": "drinks",   "device_count": 9},
    {"name": "NO.3 BAR",    "bar_type": "drinks",   "device_count": 1},
    {"name": "STAGE BAR",   "bar_type": "drinks",   "device_count": 4},
    {"name": "MALANDRINO",  "bar_type": "food",     "device_count": 2},
    {"name": "PULLED PORK", "bar_type": "food",     "device_count": 2},
    {"name": "SCROCCHIA",   "bar_type": "food",     "device_count": 2},
    {"name": "Recharge",    "bar_type": "recharge", "device_count": 4},
]

# Bars that carry a menu — matches Sundance 14's actual convention
# (confirmed by inspecting event_products on 81cc702b): every product
# on every non-service/non-recharge bar, NOT filtered by
# drink-bar-gets-drinks / food-bar-gets-food.
MENU_BAR_NAMES = {"MAIN BAR", "NO.3 BAR", "STAGE BAR", "MALANDRINO", "PULLED PORK", "SCROCCHIA"}

# ─── Products — copied verbatim from 81cc702b's 29 distinct products ────
# Products are tenant-global and reused by (name, product_type) per the
# backend's own dedup rule (see FullEventProductInput docstring) — these
# names already exist for this tenant from Sundance 14, so this will
# NOT create duplicate catalog rows, only new per-event menu rows.
PRODUCTS = [
    {"name": "ACQUA",                     "product_type": "drink",  "category": "soft_drink",       "unit": "bottle",      "default_price_cents": 200},
    {"name": "BOTTIGLIA METODO CLASSICO", "product_type": "drink",  "category": "wine_sparkling",    "unit": "bottle",      "default_price_cents": 3600},
    {"name": "BOTTIGLIA PROSECCO",        "product_type": "drink",  "category": "wine_sparkling",    "unit": "bottle",      "default_price_cents": 2800},
    {"name": "BOTTIGLIA VINO",            "product_type": "drink",  "category": "wine_red",          "unit": "bottle",      "default_price_cents": 2800},
    {"name": "DRINK",                     "product_type": "drink",  "category": "basic_cocktail",    "unit": "glass",       "default_price_cents": 1200},
    {"name": "DRINK ANALCOLICI",          "product_type": "drink",  "category": "soft_drink",        "unit": "glass",       "default_price_cents": 800},
    {"name": "GIN TONIC",                 "product_type": "drink",  "category": "basic_cocktail",    "unit": "glass",       "default_price_cents": 1200},
    {"name": "HEINEKEN",                  "product_type": "drink",  "category": "beer_draft",        "unit": "draft_glass", "default_price_cents": 700},
    {"name": "ICHNUSA NON FILT.",         "product_type": "drink",  "category": "beer_draft",        "unit": "draft_glass", "default_price_cents": 800},
    {"name": "PREMIUM",                   "product_type": "drink",  "category": "premium_cocktail",  "unit": "glass",       "default_price_cents": 1300},
    {"name": "PROSECCO",                  "product_type": "drink",  "category": "wine_sparkling",    "unit": "glass",       "default_price_cents": 700},
    {"name": "SIGNATURE",                 "product_type": "drink",  "category": "premium_cocktail",  "unit": "glass",       "default_price_cents": 1200},
    {"name": "SOFT DRINK",                "product_type": "drink",  "category": "soft_drink",        "unit": "glass",       "default_price_cents": 600},
    {"name": "SPRITZ",                    "product_type": "drink",  "category": "basic_cocktail",    "unit": "glass",       "default_price_cents": 1000},
    {"name": "VINO",                      "product_type": "drink",  "category": "wine_red",          "unit": "glass",       "default_price_cents": 700},
    {"name": "ANALCOLICI",       "product_type": "supply", "unit": "bottle", "default_price_cents": 800,  "iva_pct": 0.10, "cauzione_cents": 0},
    {"name": "Birra Heineken",   "product_type": "supply", "unit": "bottle", "default_price_cents": 700,  "iva_pct": 0.10, "cauzione_cents": 0},
    {"name": "Birra Ichnusa",    "product_type": "supply", "unit": "bottle", "default_price_cents": 800,  "iva_pct": 0.10, "cauzione_cents": 0},
    {"name": "CLASSICA",         "product_type": "supply", "unit": "bottle", "default_price_cents": 700,  "iva_pct": 0.10, "cauzione_cents": 0},
    {"name": "Cauzione Bicchiere", "product_type": "supply", "unit": "bottle", "default_price_cents": 100, "iva_pct": 0.10, "cauzione_cents": 0},
    {"name": "Cheeseburger",     "product_type": "supply", "unit": "bottle", "default_price_cents": 1200, "iva_pct": 0.10, "cauzione_cents": 0},
    {"name": "Fritto",           "product_type": "supply", "unit": "bottle", "default_price_cents": 800,  "iva_pct": 0.10, "cauzione_cents": 0},
    {"name": "Hamburger",        "product_type": "supply", "unit": "bottle", "default_price_cents": 1200, "iva_pct": 0.10, "cauzione_cents": 0},
    {"name": "Patatina L",       "product_type": "supply", "unit": "bottle", "default_price_cents": 800,  "iva_pct": 0.10, "cauzione_cents": 0},
    {"name": "Patatina S",       "product_type": "supply", "unit": "bottle", "default_price_cents": 500,  "iva_pct": 0.10, "cauzione_cents": 0},
    {"name": "Pulled",           "product_type": "supply", "unit": "bottle", "default_price_cents": 1200, "iva_pct": 0.10, "cauzione_cents": 0},
    {"name": "SAPORITA",         "product_type": "supply", "unit": "bottle", "default_price_cents": 800,  "iva_pct": 0.10, "cauzione_cents": 0},
    {"name": "Veggie",           "product_type": "supply", "unit": "bottle", "default_price_cents": 1200, "iva_pct": 0.10, "cauzione_cents": 0},
    {"name": "Veggie Burger",    "product_type": "supply", "unit": "bottle", "default_price_cents": 1200, "iva_pct": 0.10, "cauzione_cents": 0},
]


def login(client: httpx.Client) -> str:
    r = client.post(
        f"{API_BASE}/auth/login",
        data={"username": OMAR_EMAIL, "password": OMAR_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    r.raise_for_status()
    return r.json()["access_token"]


def find_existing_draft(client: httpx.Client, headers: dict) -> dict | None:
    r = client.get(f"{API_BASE}/events", headers=headers)
    r.raise_for_status()
    for ev in r.json():
        if ev["name"] == EVENT_NAME and ev["status"] == "draft":
            return ev
    return None


def get_or_create_venue(client: httpx.Client, headers: dict) -> str:
    r = client.get(f"{API_BASE}/venues", headers=headers)
    r.raise_for_status()
    for v in r.json():
        if v["name"] == VENUE_NAME:
            print(f"venue: reusing existing {VENUE_NAME!r} ({v['id']})")
            return v["id"]
    r = client.post(
        f"{API_BASE}/venues",
        headers=headers,
        json={"name": VENUE_NAME, "address": VENUE_ADDRESS, "capacity": VENUE_CAPACITY},
    )
    r.raise_for_status()
    venue = r.json()
    print(f"venue: created {VENUE_NAME!r} ({venue['id']})")
    return venue["id"]


def build_payload(venue_id: str) -> dict:
    bar_index_by_name = {b["name"]: i for i, b in enumerate(BARS)}

    menu = []
    for p_index, product in enumerate(PRODUCTS):
        for bar_name in MENU_BAR_NAMES:
            menu.append({
                "bar_index": bar_index_by_name[bar_name],
                "product_index": p_index,
                "price_cents": product["default_price_cents"],
                "is_available": True,
            })

    return {
        "event": {
            "name": EVENT_NAME,
            "venue_id": venue_id,
            "scheduled_at": SCHEDULED_AT,
            "scheduled_end_at": SCHEDULED_END_AT,
            "expected_guest_count": EXPECTED_GUEST_COUNT,
            "food_revenue_share_pct": FOOD_REVENUE_SHARE_PCT,
        },
        "bars": [
            {
                "name": b["name"],
                "bar_type": b["bar_type"],
                "device_count": b["device_count"],
                "slesh_negozio_id": None,
                "is_active": True,
            }
            for b in BARS
        ],
        "products": [
            {
                "name": p["name"],
                "product_type": p["product_type"],
                "category": p.get("category"),
                "unit": p["unit"],
                "default_price_cents": p["default_price_cents"],
                "iva_pct": p.get("iva_pct"),
                "cauzione_cents": p.get("cauzione_cents"),
            }
            for p in PRODUCTS
        ],
        "menu": menu,
        "allocations": [],  # Charge Bars UI handles this Thursday
    }


def main() -> int:
    with httpx.Client(timeout=30) as client:
        token = login(client)
        headers = {"Authorization": f"Bearer {token}"}

        existing = find_existing_draft(client, headers)
        if existing is not None:
            print(f"SKIP: '{EVENT_NAME}' DRAFT already exists: {existing['id']}")
            return 0

        venue_id = get_or_create_venue(client, headers)
        payload = build_payload(venue_id)

        r = client.post(f"{API_BASE}/events/full", headers=headers, json=payload)
        if r.status_code != 201:
            print(f"FAILED: {r.status_code} {r.text}", file=sys.stderr)
            return 1

        result = r.json()
        event_id = result["event"]["id"]
        print(f"CREATED: {EVENT_NAME} -> {event_id}")
        print(f"  bars_created={result['bars_created']} "
              f"products_created={result['products_created']} "
              f"products_reused={result['products_reused']} "
              f"menu_items_created={result['menu_items_created']} "
              f"allocations_created={result['allocations_created']}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
