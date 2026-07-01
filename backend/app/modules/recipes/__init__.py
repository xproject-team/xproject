"""Recipes module — structured composition for drink Products.

Two tables:
    recipes         header (per-drink, tenant-global)
    recipe_items    ingredient lines with qty + unit

Design decisions (locked Step 5 Q1-Q3):
- Tenant-global: one recipe per (tenant, drink_product). Event-level
  variations belong as separate Products in the catalog.
- Any product_type EXCEPT the drink itself can be an ingredient.
  Self-reference is blocked by the service layer.
- Two-table parent-child with CASCADE on recipe_items.recipe_id.

Unit handling:
- recipe_items.unit is the RECIPE UNIT (e.g., 50ml of rum even when
  Product.unit=bottle). This is a deliberate exception to the
  "Product.unit is truth" rule in bar_stock — recipes need fine-
  grained measurement independent of how the product is stocked.
- Upcoming Step 6 reconciliation will convert recipe units -> stock
  units (50ml pour = 0.0667 bottle) using a conversion table.

Numeric precision:
- qty and yield_qty are NUMERIC(10, 3): up to 9,999,999.999.
- Supports both fine pours (0.5ml bitters) and batch recipes
  (liters of punch for events).

Live-depletion status (as of Chunk 3a investigation, July 2026):
- This module does NOT drive live sale-depletion or the depletion
  alerts Omar sees during an event. That path is
  app.modules.event_storage.bar_supplier_stock_service
  (compute_bar_supplier_stock + fire_depletion_alerts), which reads
  EventCategoryIngredient rows (Catalog > Recipes tab, Chunk 2) and
  is polled live from the Dashboard via GET /events/{id}/bar-supplier-stock.
  Verified against a real LIVE Sundance 14 simulation event: 43
  (bar, supplier_product) rows computed correctly from real dispatch +
  Slesh sale data.
- recipes/recipe_items IS still wired, but only into
  RecipeDeviationDetector (F.10c.1.e) — a per-drink over-pour anomaly
  detector that compares actual vs. expected ingredient consumption
  for drinks that have a Recipe defined. No real Sundance event
  currently has Recipe rows (only a couple of dev-test rows exist),
  so this detector is dormant in practice, not because it's broken,
  but because nothing has populated a Recipe for a real drink yet.
- cascade.py's RecipeItem-based plan_ingredient_decrement (used by
  stock_transactions.service.ingest_sale) is the write path that
  would feed the deviation detector above if a Recipe existed for the
  sold drink. It is UNRELATED to EventCategoryIngredient and does not
  need to change for ECI-based depletion to work — that's already a
  fully separate, working, read-time computation.
"""
