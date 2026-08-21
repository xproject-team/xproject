"""Single source of truth for what counts as revenue, platform-wide.

Two layers, two jobs (docs/revenue-calculation-bible.md):

  1. MONEY — event_orders. `fiscal_gross_cents` on confirmed orders is
     the money-of-record from Slesh: every wristband tap, food trucks
     and no-recipe drinks included, deposits excluded (fiscal_gross =
     subtotal − deposits), VAT included. The dashboard header
     (EventKpiSummaryService) and the report headline (ReportAggregator)
     both build their euro totals from `confirmed_order_conditions` +
     `fiscal_gross_cents` — one definition, migrated together Aug 2026
     (dashboard 2026-07-05/F-01, reports Day 14).

  2. UNITS / PER-PRODUCT DETAIL — stock_transactions. event_orders has
     no line-level product data, so anything counting units or naming
     products (top product, product performance, category breakdowns,
     depletion, demand models) reads stock_transactions rows whose
     source is in REVENUE_SOURCES. Coverage is partial by design
     (unmatched catalog products and parked orders never produce lines);
     unit figures must never be presented as summing to the money total.

Before this module, REVENUE_SOURCES was independently defined in four
files (reports/aggregator, predictions/heuristic, nowcast/service,
nowcast/retrain) — a migration hazard. They all import from here now.
"""
from __future__ import annotations

from uuid import UUID

from app.modules.events.models import EventOrder

# stock_transactions sources that represent customer spend. Adjustments
# and reconciliation corrections are housekeeping, not revenue. String
# values — the transaction_source column uses values_callable, so these
# compare correctly against the native enum.
REVENUE_SOURCES = ("slesh_pos", "manual_bartender")


def confirmed_order_conditions(tenant_id: UUID, event_id: UUID) -> tuple:
    """WHERE conditions selecting the revenue-counting event_orders rows.

    confirmed_line_count > 0 excludes fully-refunded orders — the same
    filter RevenueBreakdownService and EventKpiSummaryService apply.
    Deliberately does NOT filter on bar_id: orders from POS shops not
    yet mapped to a bar (bar_id IS NULL) are real money and belong in
    every event total; surfaces that need per-bar attribution add their
    own bar_id conditions and account for the unmapped remainder
    explicitly.
    """
    return (
        EventOrder.tenant_id == tenant_id,
        EventOrder.event_id == event_id,
        EventOrder.confirmed_line_count > 0,
    )
