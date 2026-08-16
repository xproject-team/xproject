#!/usr/bin/env python3
"""create_july5_test_draft.py — rebuild the local Sundance-15-adjacent
test draft to mirror PRODUCTION Sundance 14's actual bar layout
(7 real bars, real Slesh negozio ids), discovered by querying the
Railway prod DB directly. Supersedes the earlier "Sundance 15" draft
(35bc97f5-..., deleted by delete_local_test_draft.py), which was built
from a generic Sundance 14 DRAFT template with fictional bar names and
no Slesh linkages.

THROWAWAY TEST UTILITY. LOCAL DATABASE / LOCAL API ONLY — this script
never touches Railway or prod; it POSTs to http://localhost:8000 and
reuses whatever venue row already exists in the local dev DB.

Idempotent: if "Sundance July 5 — TEST" already exists locally, prints
its id and exits without creating anything.

Usage:
    venv/bin/python backend/scripts/create_july5_test_draft.py
Requires the API server running locally (default http://localhost:8000).

─── Bar layout — verified against prod Sundance 14 (2026-06-14) ───────
The real Sundance 14 (event 6bd035a9-3ab4-4c7f-8f68-c811aef9fa47 on
prod) has 7 bars with real Slesh shop ids, queried from Railway
directly (not reproduced here — see the BARS list below). The next
real event at Villa Alberico is July 5, same venue/POS setup, so this
is a reasonable guess at Sunday's real layout — to be CONFIRMED WITH
OMAR THURSDAY, not treated as certain.

─── Product list — reused from the previous (deleted) draft ───────────
Same 29 products as create_sundance_15_draft.py (itself copied from
local Sundance 14 DRAFT 81cc702b) — nothing about the product catalog
changed, only which bars sell what. Products are tenant-global and
reused by (name, product_type); this creates zero new catalog rows.

─── Menu convention — CHANGED from the previous draft ─────────────────
The previous draft used a uniform cross product (every product on
every non-service/recharge bar). This one is type-filtered instead:
  - product_type='drink'  -> every drinks bar (Bar Main, Bar n.3, Bar Stage)
  - everything else (all 'supply'-typed food/misc items in this
    dataset — there's no distinct 'food' product_type here, food
    items were historically typed 'supply') -> every food bar
    (Malandrino, Pulled Pork, Scrocchia)
Five of those 'supply' items are drink-adjacent, not food (Birra
Heineken, Birra Ichnusa, ANALCOLICI, CLASSICA, Cauzione Bicchiere) —
they land on the food bars along with genuine food items because the
source data doesn't distinguish them from the actual food products
(Cheeseburger, Fritto, Hamburger, ...). Flagged in the report; worth
Omar's eyes Thursday if these need splitting more precisely.
"""
from __future__ import annotations

import sys

import httpx

API_BASE = "http://localhost:8000/api/v1"
OMAR_EMAIL = "omar@nomagroup.it"
OMAR_PASSWORD = "xproject2026"

EVENT_NAME = "Sundance July 5 — TEST"

# Reuse the existing "Villa Alberico" venue — do NOT create a new one.
VILLA_ALBERICO_VENUE_ID = "f50b85ba-3065-4ece-8431-d0123f5b188c"
VILLA_ALBERICO_ROMA_VENUE_ID = "bbf05bb8-f657-488b-83f7-62618cd58586"  # duplicate, cleaned up at the end

SCHEDULED_AT = "2026-07-05T18:00:00+02:00"
SCHEDULED_END_AT = "2026-07-06T04:00:00+02:00"  # same 10h duration assumption as before
EXPECTED_GUEST_COUNT = 1600
FOOD_REVENUE_SHARE_PCT = 30

# ─── Bars — real prod Sundance 14 layout, queried from Railway ─────────
BARS = [
    {"name": "Accrediti",   "bar_type": "service", "device_count": 2, "slesh_negozio_id": "6a2acfe1ee8611fa14495d38"},
    {"name": "Bar Main",    "bar_type": "drinks",  "device_count": 9, "slesh_negozio_id": "6a268ebdb1699f9e3427f113"},
    {"name": "Bar n.3",     "bar_type": "drinks",  "device_count": 1, "slesh_negozio_id": "6a293bac7cc75422806ed55c"},
    {"name": "Bar Stage",   "bar_type": "drinks",  "device_count": 4, "slesh_negozio_id": "6a2938eb8209601072d4534b"},
    {"name": "Malandrino",  "bar_type": "food",    "device_count": 2, "slesh_negozio_id": "6847fed0875ac2b6d14b9731"},
    {"name": "Pulled Pork", "bar_type": "food",    "device_count": 2, "slesh_negozio_id": "6a293c1839f290db1200d629"},
    {"name": "Scrocchia",   "bar_type": "food",    "device_count": 2, "slesh_negozio_id": "6a293bfb39f290db1200d56d"},
]
DRINKS_BAR_NAMES = {"Bar Main", "Bar n.3", "Bar Stage"}
FOOD_BAR_NAMES = {"Malandrino", "Pulled Pork", "Scrocchia"}

# ─── Products — same 29 as the previous draft ───────────────────────────
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


def build_payload() -> dict:
    bar_index_by_name = {b["name"]: i for i, b in enumerate(BARS)}

    menu = []
    for p_index, product in enumerate(PRODUCTS):
        target_bar_names = DRINKS_BAR_NAMES if product["product_type"] == "drink" else FOOD_BAR_NAMES
        for bar_name in target_bar_names:
            menu.append({
                "bar_index": bar_index_by_name[bar_name],
                "product_index": p_index,
                "price_cents": product["default_price_cents"],
                "is_available": True,
            })

    return {
        "event": {
            "name": EVENT_NAME,
            "venue_id": VILLA_ALBERICO_VENUE_ID,
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
                "slesh_negozio_id": b["slesh_negozio_id"],
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


def cleanup_duplicate_venue(client: httpx.Client, headers: dict) -> None:
    """Delete the "Villa Alberico Roma" venue created by the previous
    (now-deleted) draft, but only if nothing references it anymore."""
    r = client.get(f"{API_BASE}/events", headers=headers)
    r.raise_for_status()
    still_referenced = any(
        ev.get("venue", {}).get("id") == VILLA_ALBERICO_ROMA_VENUE_ID for ev in r.json()
    )
    if still_referenced:
        print(f"venue cleanup: SKIPPED — 'Villa Alberico Roma' ({VILLA_ALBERICO_ROMA_VENUE_ID}) "
              f"is still referenced by an event.")
        return
    # No DELETE /venues endpoint exists — venues are append-only in this
    # API. Leaving the row in place; it's just an unused duplicate, not
    # a correctness problem. Documented, not silently dropped.
    print(f"venue cleanup: 'Villa Alberico Roma' ({VILLA_ALBERICO_ROMA_VENUE_ID}) has 0 event "
          f"references, but there is no DELETE /venues endpoint to remove it via the API. "
          f"Left in place — harmless, unused row.")


def main() -> int:
    with httpx.Client(timeout=30) as client:
        token = login(client)
        headers = {"Authorization": f"Bearer {token}"}

        existing = find_existing_draft(client, headers)
        if existing is not None:
            print(f"SKIP: '{EVENT_NAME}' DRAFT already exists: {existing['id']}")
            return 0

        payload = build_payload()

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

        cleanup_duplicate_venue(client, headers)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
