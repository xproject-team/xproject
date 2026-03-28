"""Pydantic v2 request/response schemas for the anomaly detection module."""
from datetime import datetime

from pydantic import BaseModel


class AnomalyEventResponse(BaseModel):
    id: int
    event_id: int
    detector: str
    sku: str | None = None
    score: float
    description: str
    detected_at: datetime | None = None

    model_config = {"from_attributes": True}
