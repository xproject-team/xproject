"""Sundance 14 Slesh-category → ingredient-pool depletion recipe.

Locked with Hesam evening of June 13 2026 from Omar's Slesh pre-event
form + Partesa invoice 5812120214. Refined late-night June 13 once it
became clear which categories are truly single-ingredient.

Format: list of (slesh_category, supplier_sku_or_name, ml_per_sale,
        bar_name_or_None) tuples. NULL bar_name = applies to every bar
        that sells this category. A non-NULL bar_name restricts the
        rule (and the depletion math) to that bar only.

Defaults:
  threshold_pct_warn  = 70 % consumed → 🟡 alert
  threshold_pct_empty = 100 % consumed → 🔴 alert

The seeder resolves supplier_product_id by SKU (preferred) or item_name
substring match; resolves bar_id by name match. Idempotent on
(event_id, slesh_category, supplier_product_id, bar_id).
"""

# Each entry: (slesh_category, sku_or_name_substring, ml_per_sale, bar_name_or_None)
SUNDANCE_14_RECIPE: list[tuple[str, str, float, str | None]] = [
    # ─── ACCURATE single-ingredient categories ─────────────────────────
    # These rules are the only ones tied to their slesh_category, so
    # every transaction in the category definitively consumes the
    # referenced supplier_product. The depletion engine flags these
    # alerts as ACCURATE (no human verification caveat).
    #
    # GIN TONIC is exclusive to NO.3 BAR and uses ONLY the sponsored
    # GIN No 3. A premium-tonic order rings up as PREMIUM, not GIN
    # TONIC, so every GIN TONIC tx definitively consumes GIN No 3.
    ("GIN TONIC",  "GIN No 3",       45.0, "NO.3 BAR"),
    # HEINEKEN — bottle pour from the 30 L keg.
    ("HEINEKEN",   "HEINEKEN",      330.0, None),
    # ICHNUSA NON FILT. — bottle pour from the 20 L keg.
    ("ICHNUSA NON FILT.", "ICHNUSA", 330.0, None),

    # NOTE: PROSECCO + BOTTIGLIA PROSECCO + VINO + BOTTIGLIA VINO +
    # BOTTIGLIA METODO CLASSICO categories are intentionally NOT
    # tracked in this recipe. Partesa only ships 5 bottles of Prosecco
    # DOCG (allocated to spritz needs, not glass sales), and no still
    # wine is in the invoice. With no clean supply chain to deplete
    # from, those category sales fall through to the generic "no
    # recipe rule" bucket and humans eyeball the bottles instead.
    # Re-enable in a future event once a wine / prosecco-glass
    # supplier_product is on the invoice.

    # ─── WORST-CASE multi-ingredient categories ────────────────────────
    # Slesh records the category but not which exact ingredient the
    # bartender pulled. The depletion engine attributes ml to every
    # parallel rule simultaneously and fires WORST-CASE alerts so the
    # team verifies in person before restocking.

    # DRINK — 6 spirit options @ 45 ml.
    ("DRINK",      "BEEFEATER",       45.0, None),
    ("DRINK",      "WYBOROWA",        45.0, None),
    ("DRINK",      "FOUR ROSES",      45.0, None),
    ("DRINK",      "VERMOUTH",        45.0, None),
    ("DRINK",      "CAMPARI BITTER",  45.0, None),
    ("DRINK",      "OLMECA",          45.0, None),

    # SPRITZ — 5 spirit options @ 60 ml + Cuvee Brut @ 90 ml. Cuvee
    # is technically present in every spritz but kept in the
    # multi-rule pool for now; refine post-Sundance if needed.
    ("SPRITZ",     "APEROL",                60.0, None),
    ("SPRITZ",     "CAMPARI BITTER",        60.0, None),
    ("SPRITZ",     "SARTI ROSA",            60.0, None),
    ("SPRITZ",     "VENTURO",               60.0, None),
    ("SPRITZ",     "LIMONCELLO",            60.0, None),
    ("SPRITZ",     "CUVEE",                 90.0, None),

    # SIGNATURE — 4 spirit options @ 45 ml.
    ("SIGNATURE",  "WYBOROWA",        45.0, None),
    ("SIGNATURE",  "BEEFEATER",       45.0, None),
    ("SIGNATURE",  "HAVANA",          45.0, None),
    ("SIGNATURE",  "OLMECA",          45.0, None),

    # PREMIUM — 3 spirits at every drink bar (incl. NO.3 BAR).
    # Premium gin tonics ring up as PREMIUM, NOT as GIN TONIC, so the
    # sponsored GIN No 3 stays exclusive to the GIN TONIC category
    # above and never appears in PREMIUM.
    ("PREMIUM",    "ABSOLUT",         45.0, None),
    ("PREMIUM",    "GAL41",           45.0, None),
    ("PREMIUM",    "DEL MAGUEY",      45.0, None),
]


# GIN No 3 is NOT on the Partesa invoice (sponsor direct supply).
# Setup helpers create it as a SupplierProduct + dispatch to NO.3 BAR.
GIN_NO_3_SPONSOR = {
    "supplier_name": "Sundance Sponsor",
    "supplier_sku":  "SPONSOR-GIN-NO-3",
    "item_name":     "GIN No 3 70CL (Sponsor)",
    "category":      "gin",
    "default_unit":  "BO",
    "units_per_pack": 1,
    "volume_per_unit_ml": 700,
    "last_unit_price_eur": None,
    "total_bottles": 60,
    "dispatch_to_bar": "NO.3 BAR",
}
