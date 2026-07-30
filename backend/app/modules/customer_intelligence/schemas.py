"""Pydantic response schema for GET /events/{event_id}/customer-intelligence.

One response bundles four independently-degradable sections — live
guest stats, spend segments, returning guests, and the demand forecast
— because the panel must render the first three even when the fourth
is unavailable (model not trained yet, or the artifact file is
missing). See service.py for exactly how each section is built.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ConfidenceIntervalOut(BaseModel):
    lower: float
    upper: float
    half_width_pct: float
    calibrated: bool


class CategoryForecastOut(BaseModel):
    category: str
    predicted_count: float
    # true for cocktail/spritz — the Day 3 validation showed the model
    # does not beat baseline on these two categories (heat-driven
    # cocktail<->spritz substitution on hot nights; see hot_night_applied
    # below for the manual counter-adjustment). Not a live-computed
    # metric — a static flag reflecting a validated finding.
    low_confidence: bool


class NextHourForecastOut(BaseModel):
    """The venue-total forecast for the NEXT hour specifically — this is
    what ships on the panel, not predicted_final_total (the whole-event
    total), per the Day 4 scope. The band here is derived from the
    whole-event confidence_interval's half_width_pct applied
    proportionally to this hour's slice of the predicted total — there
    is no separately-fitted per-hour band; see service.py."""
    predicted_total: float
    confidence_interval: ConfidenceIntervalOut
    category_breakdown: list[CategoryForecastOut]


class DemandForecastOut(BaseModel):
    available: bool
    unavailable_reason: str | None = None
    predicted_final_total: float | None = None
    confidence: float | None = None
    confidence_interval: ConfidenceIntervalOut | None = None
    next_hour: NextHourForecastOut | None = None
    hot_night_applied: bool = False


class HourlyPredictedVsActualOut(BaseModel):
    hour_of_event: float
    predicted: float
    actual: float


class GuestCountsOut(BaseModel):
    live_identified_count: int
    projected_final: float | None
    registered_count: int
    guest_count: int
    unknown_count: int


class SpendSegmentsOut(BaseModel):
    whale_count: int
    regular_count: int
    light_count: int
    # Thresholds this response was scored against — see constants.py for
    # how they were derived (customer_sessions percentiles, not invented).
    whale_threshold_cents: int
    light_threshold_cents: int


class ReturningGuestsOut(BaseModel):
    returning_count: int
    new_count: int
    identified_total: int


class HotNightOverrideIn(BaseModel):
    enabled: bool


class HotNightOverrideOut(BaseModel):
    event_id: UUID
    hot_night_override: bool


class CustomerIntelligenceResponse(BaseModel):
    event_id: UUID
    as_of_time: datetime
    hour_offset_from_start: float | None
    guests: GuestCountsOut
    spend_segments: SpendSegmentsOut
    returning_guests: ReturningGuestsOut
    demand_forecast: DemandForecastOut
    predicted_vs_actual: list[HourlyPredictedVsActualOut]
    hot_night_override: bool
