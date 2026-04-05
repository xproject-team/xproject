"""Pydantic v2 request/response schemas for the predictions module."""
from datetime import datetime

from pydantic import BaseModel


class PredictionResponse(BaseModel):
    id: int
    event_id: int
    sku: str
    predicted_demand: float
    confidence: float
    horizon_hours: int
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
