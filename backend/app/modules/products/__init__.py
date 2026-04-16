"""Products module — tenant-scoped catalog of drinks, food, ingredients, supplies.

Core concepts:
- Unified table polymorphic on product_type (drink/food/ingredient/supply)
- Drinks carry category (Omar's 8-value taxonomy) and tier_rank (1-4 derived)
- Soft-delete via is_archived — products referenced by events/recipes/stock
  must not be hard-deleted to preserve historical integrity
- Partial unique constraint prevents duplicate active products per tenant
  (same name + product_type) while still allowing restoration after archive
"""
