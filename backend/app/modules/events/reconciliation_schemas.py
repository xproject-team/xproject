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


# POS variance status — derived per-row in reconciliation_service.
# Honest signaling: each row's status declares what the system KNOWS,
# not what it guesses.  When the menu item is generic (no recipe to
# decompose into bottles), we surface NEEDS_RECIPE rather than
# fabricating a variance number.
PosVarianceStatus = Literal[
    "NO_POS_DATA",               # row has no Slesh sales at all
    "NEEDS_RECIPE",              # POS sold this menu item but no recipe links it to bottles
    "OK_WITHIN_THRESHOLD",       # variance within +/- 5%, normal operation
    "OVER_POUR_MINOR",           # +5% to +15%: scanner > POS, mild over-pour or comp
    "OVER_POUR_MODERATE",        # +15% to +30%: investigate
    "OVER_POUR_MAJOR",           # >+30%: serious shrinkage signal
    "UNDER_SCAN_MINOR",          # -5% to -15%: POS > scanner, mild under-scan
    "UNDER_SCAN_MAJOR",          # < -15%: significant under-scan; data quality issue
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

    # ─── POS data (S5 — Slesh integration) ──────────────────────────
    # Slesh's authoritative "this product was sold this many times" count
    # for this (bar, product) pair within the event window.  None means
    # no POS data exists yet (typical at start of event, or for items
    # like cup deposits where Slesh records no sale).
    consumed_via_pos_qty:  Decimal | None = None

    # consumed_qty (scanner-observed) minus consumed_via_pos_qty (POS).
    # Positive means scanner saw more empties than POS sold sales —
    # the over-pour / comp / breakage / theft signal.
    # None when POS data is missing OR when the menu item is generic
    # (a single Slesh "Cocktail" sale cannot be decomposed into a
    # specific bottle without a recipe).
    pos_variance_qty:      Decimal | None = None

    # Honest per-row status string — describes what the variance number
    # means.  Frontend can render different cells for each status:
    #   NO_POS_DATA           -> "— no Slesh sales yet"
    #   NEEDS_RECIPE          -> "Menu item; bottle-level pending"
    #   OK_WITHIN_THRESHOLD   -> green check
    #   OVER_POUR_*           -> orange/red warning, sized by tier
    #   UNDER_SCAN_*          -> blue info pill, sized by tier
    pos_variance_status:   PosVarianceStatus = "NO_POS_DATA"


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
    missing_pos_data:          bool       # True when no POS data exists for the event at all

    # ─── POS rollup counters (S5) ───────────────────────────────────
    # Helps Omar see at a glance: "out of 47 rows, 12 are generic menu
    # items we can't decompose, 31 are OK, 4 are flagged for over-pour."
    pos_pending_recipes_count: int = 0     # # of rows in NEEDS_RECIPE state
    pos_ok_count:              int = 0     # # of rows in OK_WITHIN_THRESHOLD
    pos_over_pour_count:       int = 0     # # of rows in any OVER_POUR_* state
    pos_under_scan_count:      int = 0     # # of rows in any UNDER_SCAN_* state


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
