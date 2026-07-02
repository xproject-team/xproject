"""Pydantic response schema for GET /events/{event_id}/revenue-forecast.

Deliberately separate from app/modules/predictions/schemas.py's
ConfidenceTier ("low"/"medium"/"high") — that type belongs to the
pre-event, guest-count-scaled heuristic predictor (a different domain:
planning forecast, generated on-demand, persisted + versioned to the
predictions table). This is a live, in-event, stateless nowcast
computed fresh on every request from actual partial-night revenue —
not persisted, not the same confidence semantics. Sharing the type
would suggest they're interchangeable; they aren't.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

NowcastConfidenceTier = Literal["early", "directional", "trustworthy"]


def confidence_tier(confidence: float) -> NowcastConfidenceTier:
    if confidence < 0.5:
        return "early"
    if confidence < 0.8:
        return "directional"
    return "trustworthy"


class PredictedCurvePoint(BaseModel):
    hour_offset: float
    cumulative_revenue_eur: float


class HistoricalRange(BaseModel):
    min: float
    max: float


class RevenueForecastResponse(BaseModel):
    event_id: UUID
    as_of_time: datetime
    hour_offset_from_start: float
    current_revenue_eur: float
    predicted_final_revenue_eur: float
    predicted_curve: list[PredictedCurvePoint]
    confidence: float
    vs_historical_avg_eur: float
    historical_range_eur: HistoricalRange
    historical_n: int
    confidence_tier: NowcastConfidenceTier
