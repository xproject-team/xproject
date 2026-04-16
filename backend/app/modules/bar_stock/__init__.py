"""bar_stock module — per-event, per-bar, per-product inventory ledger.

Each bar_stock row tracks three quantities through the event lifecycle:

    allocated_qty  ──(before event)──▶  current_qty  ──(after event)──▶  returned_qty
                                           │
                                   (consumed by bartenders)

Reconciliation formula (Step 6 will operationalize this):
    expected_consumption = allocated_qty - current_qty - returned_qty
    actual_consumption   = SUM(stock_transactions WHERE action=consume)
    anomaly              = |expected - actual|

Unit is inherited from Product.unit (not stored on this table).
"""
