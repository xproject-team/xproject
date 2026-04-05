"""Pydantic v2 request/response schemas for the events module."""
from datetime import datetime

from pydantic import BaseModel


class EventCreate(BaseModel):
    name: str
    venue: str


class EventResponse(BaseModel):
    id: int
    name: str
    venue: str
    status: str
    created_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None

    model_config = {"from_attributes": True}
