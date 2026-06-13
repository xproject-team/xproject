"""Sundance 14 Slesh-category → ingredient-pool depletion recipe.

Locked with Hesam evening of June 13 2026 from Omar's Slesh pre-event
form + Partesa invoice 5812120214.

Format: list of (slesh_category, supplier_sku_or_name, ml_per_sale,
        bar_name_or_None) tuples. NULL bar_name = applies to every bar
        that sells this category.

Defaults:
  threshold_pct_warn  = 70 % consumed → 🟡 alert
  threshold_pct_empty = 100 % consumed → 🔴 alert

The seeder resolves supplier_product_id by SKU (preferred) or item_name
substring match; resolves bar_id by name match. Idempotent on
(event_id, slesh_category, supplier_product_id, bar_id).
"""

# Each entry: (slesh_category, sku_or_name_substring, ml_per_sale, bar_name_or_None)
SUNDANCE_14_RECIPE: list[tuple[str, str, float, str | None]] = [
    # ─── GIN TONIC — single ingredient ────────────────────────────────
    ("GIN TONIC",  "BEEFEATER",       45.0, None),

    # ─── DRINK — 6 spirits, worst-case deplete all ────────────────────
    ("DRINK",      "BEEFEATER",       45.0, None),
    ("DRINK",      "WYBOROWA",        45.0, None),
    ("DRINK",      "FOUR ROSES",      45.0, None),
    ("DRINK",      "VERMOUTH",        45.0, None),
    ("DRINK",      "CAMPARI BITTER",  45.0, None),
    ("DRINK",      "OLMECA",          45.0, None),

    # ─── SPRITZ — 5 spirit options (60 ml) + Cuvee Brut (90 ml) ──────
    ("SPRITZ",     "APEROL",                60.0, None),
    ("SPRITZ",     "CAMPARI BITTER",        60.0, None),
    ("SPRITZ",     "SARTI ROSA",            60.0, None),
    ("SPRITZ",     "VENTURO",               60.0, None),
    ("SPRITZ",     "LIMONCELLO",            60.0, None),
    ("SPRITZ",     "CUVEE",                 90.0, None),  # B-SIMPLE CUVEE' BRUT 75CL

    # ─── SIGNATURE — 4 spirits, worst-case ────────────────────────────
    ("SIGNATURE",  "WYBOROWA",        45.0, None),
    ("SIGNATURE",  "BEEFEATER",       45.0, None),
    ("SIGNATURE",  "HAVANA",          45.0, None),
    ("SIGNATURE",  "OLMECA",          45.0, None),

    # ─── PREMIUM (all drink bars) — 3 spirits, worst-case ────────────
    ("PREMIUM",    "ABSOLUT",         45.0, None),
    ("PREMIUM",    "GAL41",           45.0, None),
    ("PREMIUM",    "DEL MAGUEY",      45.0, None),

    # ─── PREMIUM (NO.3 BAR exclusive) — GIN No 3 sponsor ─────────────
    ("PREMIUM",    "GIN No 3",        45.0, "NO.3 BAR"),

    # ─── PROSECCO (standalone €7 glass) — 150 ml pour ────────────────
    ("PROSECCO",   "PROSECCO DOCG",  150.0, None),

    # ─── HEINEKEN — 1 bottle pour (330 ml) per sale ──────────────────
    ("HEINEKEN",   "HEINEKEN",       330.0, None),

    # ─── ICHNUSA NON FILT. — 1 bottle pour per sale ──────────────────
    ("ICHNUSA NON FILT.", "ICHNUSA", 330.0, None),
]


# GIN No 3 is NOT on the Partesa invoice (sponsor direct supply).
# Setup helpers must create it as a SupplierProduct + dispatch to NO.3 BAR.
GIN_NO_3_SPONSOR = {
    "supplier_name": "Sundance Sponsor",
    "supplier_sku":  "SPONSOR-GIN-NO-3",
    "item_name":     "GIN No 3 70CL (Sponsor)",
    "category":      "gin",
    "default_unit":  "BO",
    "units_per_pack": 1,
    "volume_per_unit_ml": 700,
    "last_unit_price_eur": None,  # sponsor — free supply
    "total_bottles": 60,
    "dispatch_to_bar": "NO.3 BAR",
}
