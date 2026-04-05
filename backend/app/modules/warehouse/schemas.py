"""Pydantic v2 request/response schemas for the warehouse module."""
from datetime import datetime

from pydantic import BaseModel


class ScanRequest(BaseModel):
    barcode: str
    action: str  # receive | dispatch | audit
    quantity: int = 1


class ScanEventResponse(BaseModel):
    id: int
    event_id: int
    barcode: str
    sku: str | None = None
    action: str
    quantity: int
    scanned_at: datetime | None = None

    model_config = {"from_attributes": True}
