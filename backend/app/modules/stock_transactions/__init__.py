"""stock_transactions module — append-only ledger of all inventory changes.

Every stock-changing event in the system (sale, manual adjustment,
reconciliation correction) produces one or more rows in this table.

The ledger is the source of truth for:
- Revenue aggregation (Dashboard revenue tiles)
- Expected vs. actual depletion (reconciliation engine)
- Per-bar / per-product sales analytics
- Anomaly detection (deficit_qty != 0 rows)

Parent-child structure:
- A sale of 1 Mojito writes 1 PARENT row (product_id=Mojito, source=slesh_pos)
  plus N CHILD rows (one per recipe ingredient) linked via parent_transaction_id
- Standalone transactions (manual adjustments, reconciliation corrections)
  have parent_transaction_id = NULL

Append-only discipline:
- Rows are INSERT-only. Never UPDATE or DELETE.
- Corrections to mistakes are NEW rows (source=reconciliation_correction)
  that reference the bad row in a note field.
"""
