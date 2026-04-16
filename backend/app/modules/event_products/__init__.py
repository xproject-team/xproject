"""Event-Products module — menus per event.

Each event_product row represents a catalog Product being sold at a
specific Bar within a specific Event, with event-level price and
optional tier_rank override.

Relationships:
- event_products.event_id    -> events.id    (CASCADE on event deletion)
- event_products.bar_id      -> bars.id      (CASCADE on bar deletion)
- event_products.product_id  -> products.id  (RESTRICT — catalog protected)

Unique constraint: one (event, bar, product) triple can appear at most once.
"""
