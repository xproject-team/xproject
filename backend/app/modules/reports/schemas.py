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
    """Top-line revenue numbers shown on Section 2."""
    total_revenue: Decimal
    revenue_per_hour: Decimal
    revenue_per_bar_avg: Decimal
    top_product_name: str | None = None
    top_product_units: int | None = None
    peak_hour_start: datetime | None = None   # HH:00 boundary
    peak_hour_revenue: Decimal | None = None


class ReportBarRevenue(BaseModel):
    """One row in the per-bar revenue breakdown. Sorted by rank ascending."""
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

    # Body — matches the 4 content pages in spec §3
    event: ReportEventInfo
    revenue_kpis: ReportRevenueKpis
    bar_revenues: list[ReportBarRevenue] = Field(default_factory=list)
    stock_rows: list[ReportStockRow] = Field(default_factory=list)
    alerts: list[ReportAlertRow] = Field(default_factory=list)
    narrative: ReportNarrative


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
