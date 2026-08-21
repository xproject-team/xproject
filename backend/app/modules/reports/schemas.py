"""Pydantic v2 request/response schemas for the Reports module.

These schemas are the contract between the backend API and:
  - Frontend TanStack Query hooks (1:1 mapped to TS interfaces in mockData.ts)
  - The ReportAggregator service (internal snapshot shape)
  - The NarrativeEngine (consumer of ReportData, producer of ReportNarrative)
  - The PDF renderer (Phase 2 — consumes ReportData to lay out pages)

Every field name MUST mirror the ORM model exactly; the frontend will define
TypeScript interfaces with the same names. Drift here breaks the contract-first
architecture that lets us swap mock → real with a one-line change per hook.

Spec: docs/report-module-spec.md §4.2 + §4.3.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums (literal-typed for runtime + IDE safety) ───────────────────────────
# Mirror the Postgres enums declared in h1_add_reports.py migration.
ReportStatus = Literal["pending", "generating", "ready", "failed"]
ReportLanguage = Literal["it", "en"]

# Re-declared here for convenience — sourcing from alerts.schemas would create
# a circular import risk. The string values MUST match alerts.schemas exactly.
AlertType = Literal["depletion", "anomaly", "discrepancy", "system"]
AlertSeverity = Literal["info", "warning", "critical", "anomaly"]
AlertAudience = Literal["owner_only", "owner_and_manager"]


# ─── Leaf DTOs (the building blocks of ReportData) ────────────────────────────

class ReportEventInfo(BaseModel):
    """Event identity + timing metadata rendered on the cover page."""
    event_id: UUID
    event_name: str
    venue_name: str
    started_at: datetime
    ended_at: datetime
    duration_hours: float
    bars_count: int
    guests_served: int | None = None   # NULL until ticketing integration
    expected_guest_count: int | None = None


class ReportRevenueKpis(BaseModel):
    """Top-line revenue numbers shown on Section 2.

    Since the Day 14 migration, the euro figures come from event_orders
    (fiscal_gross_cents on confirmed orders — the money-of-record from
    Slesh, matching the dashboard header exactly; deposits excluded, VAT
    included). top_product_* stays on stock_transactions: event_orders
    has no per-product line detail. See events/revenue.py.

    revenue_per_bar_avg divides only BAR-ATTRIBUTED revenue by the count
    of bars that sold — unmapped orders (no bar) are excluded from both
    sides rather than smeared across bars. unmapped_revenue surfaces
    that remainder explicitly; it is included in total_revenue.
    """
    total_revenue: Decimal
    revenue_per_hour: Decimal
    revenue_per_bar_avg: Decimal
    # Confirmed-order revenue whose POS shop has no bar mapping yet.
    # Included in total_revenue; not attributable to any bar_revenues
    # row. 0 on reports generated before the Day 14 migration.
    unmapped_revenue: Decimal = Decimal(0)
    top_product_name: str | None = None
    top_product_units: int | None = None
    peak_hour_start: datetime | None = None   # HH:00 boundary
    peak_hour_revenue: Decimal | None = None


class ReportBarRevenue(BaseModel):
    """One row in the per-bar revenue breakdown. Sorted by rank ascending.

    revenue_pct is of total_revenue (which includes unmapped orders), so
    rows can legitimately sum to less than 100% — the remainder is
    ReportRevenueKpis.unmapped_revenue, never silently redistributed.
    transactions_count counts confirmed ORDERS since the Day 14
    migration (event_orders rows); on older reports it counted
    stock_transactions lines.
    """
    bar_id: UUID
    bar_name: str
    revenue: Decimal
    revenue_pct: float   # of total, 0.0 – 100.0
    transactions_count: int
    rank: int            # 1 = highest-earning bar


class ReportStockRow(BaseModel):
    """One product-at-one-bar row for Section 3 (Stock Reality Check)."""
    bar_id: UUID
    bar_name: str
    product_id: UUID
    product_name: str
    opening_qty: Decimal
    closing_qty: Decimal
    consumed_qty: Decimal
    burn_rate_per_hour: Decimal
    stock_out_occurred: bool
    stock_out_time: datetime | None = None
    consumption_vs_plan_pct: float | None = None   # NULL if no plan set


class ReportAlertRow(BaseModel):
    """One alert entry for Section 4 (Alerts Timeline)."""
    alert_id: UUID
    alert_type: AlertType
    severity: AlertSeverity
    bar_id: UUID | None = None
    bar_name: str | None = None
    title: str
    owner_message: str
    fired_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by_name: str | None = None
    audience: AlertAudience


class ReportGuestKpis(BaseModel):
    """Section A — Guests. Sourced from customer_sessions/customer_purchases.

    identified_total is a FLOOR on attendance, not attendance itself —
    it counts guests who made an identified purchase, not everyone who
    walked in. The only attendance NUMBER this system has at all is
    ReportEventInfo.expected_guest_count, which is a planning estimate,
    not a measurement (see caveat on ReportRevenueDecomposition).
    """
    available: bool = True
    unavailable_reason: str | None = None
    identified_total: int = 0
    registered_count: int = 0
    guest_count: int = 0
    unknown_count: int = 0
    whale_count: int = 0
    regular_count: int = 0
    light_count: int = 0
    whale_threshold_cents: int = 0
    light_threshold_cents: int = 0
    returning_count: int = 0
    new_count: int = 0


class ReportForecastHourRow(BaseModel):
    """One hour-of-event checkpoint in Section B's predicted-vs-actual series."""
    hour_of_event: float
    predicted: float
    actual: float
    lower: float
    upper: float
    within_band: bool


class ReportForecastAccuracy(BaseModel):
    """Section B — Forecast vs. Actual, from the demand model
    (predictions/demand/). available=False (with unavailable_reason) is
    the normal, expected state for any tenant/event that hasn't trained
    a demand model yet — this must never block the rest of the report.
    """
    available: bool = True
    unavailable_reason: str | None = None
    predicted_final_total: float | None = None
    actual_final_total: float | None = None
    hours: list[ReportForecastHourRow] = Field(default_factory=list)
    # "actual fell within the predicted range in N of M hours" — the
    # single honest forecast-quality statement, not an error percentage.
    band_hits: int | None = None
    band_hours_total: int | None = None


class ReportComparisonMetric(BaseModel):
    """One row in Section C's comparison table — e.g. 'Total Revenue'."""
    label: str
    # How renderers should format the values: 'eur' → currency, 'count'
    # → plain integer. None on reports generated before the Day 14
    # migration — renderers fall back to plain numeric formatting.
    unit: Literal["eur", "count"] | None = None
    current_value: float | None = None
    previous_event_value: float | None = None
    previous_event_delta_pct: float | None = None
    season_avg_value: float | None = None
    season_avg_delta_pct: float | None = None


class ReportComparison(BaseModel):
    """Section C — Event-over-Event Comparison.

    Revenue/peak-hour metrics are available for every past event (they
    were already in every historical data_json). Guest/category/
    decomposition metrics are only available for events whose reports
    were generated after this feature shipped — NOT backfilled by
    regenerating old reports (that would risk changing numbers Omar has
    already seen). guest_metrics_available_from documents the cutoff so
    the report can say so plainly rather than silently show fewer rows.
    """
    available: bool = True
    unavailable_reason: str | None = None
    previous_event_name: str | None = None
    previous_event_date: datetime | None = None
    season_avg_n_events: int = 0
    metrics: list[ReportComparisonMetric] = Field(default_factory=list)
    guest_metrics_available_from: str | None = None
    # True when the previous event / season set includes reports whose
    # revenue was measured with the pre-Day-14 method (stock movements)
    # — deltas then carry a small definitional component (~2% on
    # reconciled events, more if the old report was stale). Renderers
    # show a footnote; the narrative skips its revenue-vs-previous
    # sentence rather than state a mixed-method delta as fact.
    mixed_revenue_sources: bool = False


class ReportRevenueDecomposition(BaseModel):
    """Section D — Revenue Decomposition: attendance x purchase rate x
    orders/purchaser x AOV.

    estimated_attendance is expected_guest_count, verbatim — a planning
    figure, not a measured fact. purchase_rate_pct is therefore ALSO an
    estimate (purchasers / an estimate), and must be presented as one
    everywhere this is shown (PDF label, narrative wording, frontend) —
    never stated as a measured conversion rate.
    """
    available: bool = True
    unavailable_reason: str | None = None
    estimated_attendance: int | None = None
    purchasers: int | None = None
    purchase_rate_pct: float | None = None
    orders_per_purchaser: float | None = None
    average_order_value_cents: int | None = None
    implied_revenue_cents: int | None = None
    actual_revenue_cents: int | None = None


class ReportProductRow(BaseModel):
    """One row in Section E's top/lowest-selling product tables."""
    product_id: UUID
    product_name: str
    category: str | None = None
    units_sold: int
    revenue_cents: int
    category_revenue_share_pct: float | None = None


class ReportProductPerformance(BaseModel):
    """Section E — Top and Lowest-Selling Products.

    "lowest_selling", deliberately not "bottom"/"underperforming" —
    excludes products with zero units sold (never listed = not on the
    menu, a different situation from selling weakly). The narrative
    raises these as a question (new item? priced high? quiet bar?), not
    a verdict.
    """
    top_products: list[ReportProductRow] = Field(default_factory=list)
    lowest_selling_products: list[ReportProductRow] = Field(default_factory=list)


class ReportNarrative(BaseModel):
    """The three prose sections of Section 1 (Executive Narrative).

    Rendered by the NarrativeEngine from paired IT+EN templates. Content is
    already language-resolved at render time — the `language` field on the
    parent ReportData tells consumers which one this is.
    """
    what_happened: str
    what_worked: str
    what_next: list[str] = Field(default_factory=list)   # 3–4 bullets


# ─── Snapshot (the full ReportData blob stored in reports.data_json) ──────────

class ReportData(BaseModel):
    """Immutable snapshot of everything rendered into one report.

    Once a report reaches status='ready', this structure is frozen. Any later
    correction creates a NEW report row with version+1 (see spec §5.4).
    """
    # Header
    report_id: UUID
    version: int
    language: ReportLanguage
    generated_at: datetime
    # Which method produced the euro figures. 'event_orders' from the
    # Day 14 migration onward; None on older frozen snapshots (which
    # were computed from stock_transactions). Never backfilled — old
    # reports keep their numbers AND their label.
    revenue_source: Literal["stock_transactions", "event_orders"] | None = None

    # Body — matches the content pages in spec §3
    event: ReportEventInfo
    revenue_kpis: ReportRevenueKpis
    bar_revenues: list[ReportBarRevenue] = Field(default_factory=list)
    stock_rows: list[ReportStockRow] = Field(default_factory=list)
    alerts: list[ReportAlertRow] = Field(default_factory=list)
    narrative: ReportNarrative

    # New sections (Reports feature improvement, 2026-07-31). Optional
    # with no default value collision risk: old data_json blobs simply
    # lack these keys, and Pydantic fills None — every consumer (PDF,
    # narrative templates, frontend) must treat None as "not computed
    # for this report" (older report) same as available=False (computed,
    # but the underlying data wasn't there), not as an error.
    guests: ReportGuestKpis | None = None
    forecast_accuracy: ReportForecastAccuracy | None = None
    comparison: ReportComparison | None = None
    revenue_decomposition: ReportRevenueDecomposition | None = None
    product_performance: ReportProductPerformance | None = None


# ─── API envelopes (wire format for REST endpoints) ───────────────────────────

class ReportSummary(BaseModel):
    """Lightweight row for the Reports index list view.

    Denormalizes a few fields from data_json so the list card can render
    without N+1 fetches of the full snapshot.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    event_name: str
    event_started_at: datetime
    event_ended_at: datetime
    version: int
    status: ReportStatus
    language: ReportLanguage
    generated_at: datetime | None = None

    # Denormalized fields for list-card rendering
    total_revenue: Decimal | None = None
    alerts_count: int | None = None
    top_bar_name: str | None = None


class ReportResponse(BaseModel):
    """Detail view returned by GET /reports/{id}. Contains the full snapshot."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    version: int
    superseded_by: UUID | None = None
    status: ReportStatus
    language: ReportLanguage
    generated_at: datetime | None = None
    data: ReportData | None = None   # NULL while status in (pending, generating)


class PortfolioKpis(BaseModel):
    """Cross-event metrics for the Portfolio Insights Strip on /reports.

    Drives the 4-tile header that replaces the old blue 'Current Event' card.
    Computed on-demand from the completed-reports set; not stored.
    """
    total_events_completed: int
    lifetime_revenue: Decimal
    avg_event_revenue: Decimal
    best_event_name: str | None = None
    best_event_revenue: Decimal | None = None

    # Comparisons vs previous period
    events_delta_vs_last_quarter: int = 0
    revenue_delta_pct_yoy: float | None = None   # None if no YoY baseline
    avg_revenue_delta_vs_last_quarter: Decimal | None = None


# ─── Request bodies ───────────────────────────────────────────────────────────

class GenerateReportRequest(BaseModel):
    """Body of POST /reports/generate — on-demand generation."""
    event_id: UUID
    language: ReportLanguage = "it"


class RegenerateReportRequest(BaseModel):
    """Body of POST /reports/{id}/regenerate — admin-only, creates v+1."""
    language: ReportLanguage | None = None   # default: inherit from original
