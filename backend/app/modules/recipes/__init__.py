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
"""
