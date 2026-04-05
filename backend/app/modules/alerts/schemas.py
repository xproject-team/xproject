"""Pydantic v2 request/response schemas for the alerts module."""
from datetime import datetime

from pydantic import BaseModel


class AlertResponse(BaseModel):
    id: int
    event_id: int
    rule_name: str
    severity: str
    message: str
    acknowledged: bool
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
