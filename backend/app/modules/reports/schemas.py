"""Pydantic v2 request/response schemas for the reports module."""
from datetime import datetime

from pydantic import BaseModel


class ReportResponse(BaseModel):
    id: int
    event_id: int
    title: str
    narrative: str | None = None
    pdf_path: str | None = None
    generated_at: datetime | None = None

    model_config = {"from_attributes": True}
