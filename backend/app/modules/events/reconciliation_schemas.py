"""
Reconciliation report — response schemas.

Maps the per-(bar, product) and per-(product) views produced by
reconciliation_service.compute_report() into the JSON contract the
frontend consumes.

Sundance-safety property: all numeric quantities are Decimal serialized
as strings to preserve precision across the wire (avoids JS float-loss
on quantities like 0.1L pours that can otherwise become 0.09999…).
"""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# ─── Flag enum (string literal) ─────────────────────────────────────────────

DeliveryGapFlag = Literal[
    "DELIVERY_GAP_MINOR",
    "DELIVERY_GAP_MODERATE",
    "DELIVERY_GAP_MAJOR",
]


# ─── Per-row response (per bar × product) ──────────────────────────────────

class ReconciliationRow(BaseModel):
    """One row of the reconciliation grid, scoped to a specific
    bar-product pair within the event window.

    Includes only pairs with at least one DISPATCH or CONSUMED scan
    (no zero-everything rows — reduces noise per design discussion)."""

    model_config = ConfigDict(json_encoders={Decimal: str})

    bar_id:        UUID
    bar_name:      str
    product_id:    UUID
    product_name:  str

    # From DISPATCH scans (Mode B — Manager confirms bottle arrived at bar)
    arrived_qty:   Decimal

    # From CONSUMED scans (Mode C — Bartender disposed of empty bottle)
    consumed_qty:  Decimal

    # arrived - consumed. Positive = expected leftover stock at bar.
    # Negative would indicate more empties scanned than arrivals — a
    # data-quality red flag in itself (operator scanned an empty for a
    # product they never received).
    net_qty:       Decimal

    # Reserved for future flags (over-pour signal once POS is wired).
    # Phase 6 MVP: row-level flags stay empty; gaps are reported at the
    # event level (where ground-truth dispatched_qty lives).
    flags:         list[str] = []


# ─── Event-level gap (per product, across all bars) ────────────────────────

class EventProductGap(BaseModel):
    """Per-product warehouse-vs-event reconciliation. dispatched_qty is
    only stored per (event, product) in warehouse_allocations, NOT per
    bar — so this is the honest level at which to compute delivery gap.

    Includes the worst-case pattern (dispatched > 0 but total_arrived == 0)
    as DELIVERY_GAP_MAJOR — that's the theft-in-transit / manager-forgot-
    to-scan red flag we explicitly want to surface."""

    model_config = ConfigDict(json_encoders={Decimal: str})

    product_id:              UUID
    product_name:            str

    # From warehouse_allocations.dispatched_qty (warehouse-side truth)
    dispatched_qty:          Decimal

    # SUM of DISPATCH scans across all bars for this product
    total_arrived_at_event:  Decimal

    # dispatched_qty - total_arrived_at_event. Positive means missing
    # bottles in transit. Zero or negative means OK (negative would be
    # weird — more scanned than sent — but mathematically possible
    # if manual entry was used for items not in dispatched stock).
    delivery_gap:            Decimal

    # delivery_gap / dispatched_qty * 100, rounded to 2 decimals.
    # Null when dispatched_qty == 0 (division-by-zero guard).
    gap_pct:                 float | None

    flag:                    DeliveryGapFlag | None


# ─── Summary totals ────────────────────────────────────────────────────────

class ReconciliationTotals(BaseModel):
    """Aggregate counters useful for top-of-page summary cards."""

    model_config = ConfigDict(json_encoders={Decimal: str})

    active_rows:               int        # number of (bar, product) pairs with activity
    total_arrived:             Decimal    # SUM of all arrived_qty across rows
    total_consumed:            Decimal    # SUM of all consumed_qty across rows
    event_delivery_gap_count:  int        # # of EventProductGap entries with non-null flag
    missing_pos_data:          bool       # True until Slesh sandbox is wired


class ReconciliationSummary(BaseModel):
    event_level_gaps:  list[EventProductGap]
    totals:            ReconciliationTotals


# ─── Top-level response envelope ───────────────────────────────────────────

class ReconciliationReport(BaseModel):
    """The full reconciliation-report payload returned by
    GET /api/v1/events/{event_id}/reconciliation-report."""

    event_id:           UUID
    event_name:         str
    event_status:       str           # mirrors event_status enum: draft/active/live/completed/cancelled
    event_started_at:   datetime | None
    event_ended_at:     datetime | None
    generated_at:       datetime

    rows:               list[ReconciliationRow]
    summary:            ReconciliationSummary
