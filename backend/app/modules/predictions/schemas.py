"""Pydantic v2 request/response schemas for the Predictions module.

These schemas are the contract between the backend API and:
  - Frontend TanStack Query hooks (1:1 mapped to TS interfaces in usePredictions.ts)
  - The HeuristicPredictor today / MLPredictor in Track 2
  - Downstream consumers (Reports module, dashboards)

Field names MUST mirror the ORM model exactly; the frontend will define
TypeScript interfaces with the same names. Drift here breaks the
contract-first architecture that lets us swap the prediction engine
(heuristic → ML) with zero frontend changes.

Spec: docs/predictions-module-spec.md §4.2 + §4.3.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Reuse from reports module — identical shape, no duplication.
from app.modules.reports.schemas import ReportEventInfo


# ─── Enums (literal-typed for runtime + IDE safety) ───────────────────────────
# Mirror the Postgres enums declared in i1_add_predictions.py migration.
PredictionStatus = Literal[
    "pending", "generating", "ready", "failed", "insufficient_data",
]
PredictorType = Literal["heuristic", "ml"]
ConfidenceTier = Literal["low", "medium", "high"]

# Reused for category_demand — must match product catalog tiers.
ProductCategory = Literal["beer", "spirits", "wine", "mixers", "cocktails"]

# Reused for demand-trend labeling.
DemandTrend = Literal["up", "stable", "down"]


# ─── Leaf DTOs ────────────────────────────────────────────────────────────────

class PredictionRange(BaseModel):
    """Every numeric prediction is a range, not a point.

    Wide ranges signal low confidence; narrow ranges signal high confidence.
    Display format: "140 units (range 110-170, 80% confidence)".
    """
    low: Decimal
    mid: Decimal
    high: Decimal
    confidence_pct: float = Field(ge=0.0, le=100.0)


class PredictionBarRevenue(BaseModel):
    """Per-bar slice of the total revenue prediction."""
    bar_id: UUID
    bar_name: str
    revenue: PredictionRange


class PredictionBarStaff(BaseModel):
    """Per-bar staff recommendation."""
    bar_id: UUID
    bar_name: str
    bartenders: PredictionRange


class PredictionRevenue(BaseModel):
    """Total + per-bar revenue forecast. Matches spec §3.2 card #1."""
    total: PredictionRange
    per_bar: list[PredictionBarRevenue] = Field(default_factory=list)
    vs_last_event_pct: float | None = None   # None if first event


class PredictionCategoryDemand(BaseModel):
    """Per-category demand forecast. Matches spec §3.2 card #2."""
    category: ProductCategory
    units: PredictionRange
    trend: DemandTrend


class PredictionPeakHour(BaseModel):
    """Predicted peak-demand window. Matches spec §3.2 card #3.

    window_start/end are datetime values in the event's local timezone.
    The UI displays them as HH:MM. predicted_revenue_share_pct is the
    % of total event revenue expected to land in this hour.
    """
    window_start: datetime
    window_end: datetime
    predicted_revenue_share_pct: float = Field(ge=0.0, le=100.0)


class PredictionStaff(BaseModel):
    """Staff recommendation. Matches spec §3.2 card #4."""
    total_bartenders: PredictionRange
    per_bar: list[PredictionBarStaff] = Field(default_factory=list)


class PredictionRiskFlag(BaseModel):
    """Per-product stock-out risk. Matches spec §3.2 card #5.

    stockout_probability is 0.0–1.0 (not a percentage). Frontend formats it.
    predicted_stockout_time is when the product would likely run out if
    the forecast demand materializes and no restock happens.
    """
    product_id: UUID
    product_name: str
    bar_id: UUID
    bar_name: str
    stockout_probability: float = Field(ge=0.0, le=1.0)
    predicted_stockout_time: datetime | None = None


# ─── Snapshot (the full PredictionData blob stored in predictions.data_json) ──

class PredictionData(BaseModel):
    """Immutable snapshot of everything rendered into one prediction.

    Once a prediction reaches status='ready', this structure is frozen. Any
    later regeneration creates a NEW predictions row with version+1.
    See spec §6 for the lifecycle.
    """
    # Header
    prediction_id: UUID
    version: int
    generated_at: datetime
    based_on_event_count: int
    confidence_tier: ConfidenceTier

    # Event context
    event: ReportEventInfo

    # The 5 predictions (spec §3.2)
    revenue: PredictionRevenue
    category_demand: list[PredictionCategoryDemand] = Field(default_factory=list)
    peak_hour: PredictionPeakHour | None = None
    staff: PredictionStaff
    risk_flags: list[PredictionRiskFlag] = Field(default_factory=list)


class PredictionInsufficientData(BaseModel):
    """Sentinel returned by BasePredictor when history is below threshold.

    Not an error — a valid outcome. Service layer persists it as
    status='insufficient_data' with insufficient_data_message populated.
    Frontend renders the calm empty state from spec §3.1.
    """
    reason: str   # e.g. "Need at least 1 completed event"
    user_message: str   # Italian/English message for the UI
    events_available: int
    events_required: int


# ─── API envelopes ────────────────────────────────────────────────────────────

class PredictionSummary(BaseModel):
    """List view — lightweight row for /predictions/events/{id}/history."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    event_name: str
    version: int
    status: PredictionStatus
    predictor_type: PredictorType
    confidence_tier: ConfidenceTier
    based_on_event_count: int
    generated_at: datetime | None = None


class PredictionResponse(BaseModel):
    """Detail view — full PredictionResponse including inline PredictionData."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    version: int
    superseded_by: UUID | None = None
    status: PredictionStatus
    predictor_type: PredictorType
    confidence_tier: ConfidenceTier
    based_on_event_count: int
    generated_at: datetime | None = None
    data: PredictionData | None = None
    insufficient_data_message: str | None = None


# ─── Request bodies ───────────────────────────────────────────────────────────

class GeneratePredictionRequest(BaseModel):
    """Body of POST /predictions/generate — on-demand generation."""
    event_id: UUID


class RegeneratePredictionRequest(BaseModel):
    """Body of POST /predictions/{id}/regenerate.

    Empty for now — future versions may accept overrides. Kept as a
    typed class so future fields are non-breaking additions.
    """
    pass
