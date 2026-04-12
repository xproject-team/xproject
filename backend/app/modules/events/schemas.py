"""Pydantic v2 request/response schemas for the events module.

Conventions:
- *Create schemas define what the CLIENT sends. No tenant_id, no id, no timestamps.
- *Response schemas define what the SERVER returns. Includes all public fields.
- model_config = {"from_attributes": True} lets us build schemas from ORM objects.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.events.models import EventStatus


# ─── Venue (read-only shape for now; full CRUD in a later phase) ────────
class VenueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    address: str | None = None
    capacity: int | None = None


# ─── Event ──────────────────────────────────────────────────────────────
class EventCreate(BaseModel):
    """Payload for POST /api/v1/events. Client-provided fields only."""
    name: str = Field(..., min_length=1, max_length=255)
    venue_id: UUID
    expected_guest_count: int | None = Field(default=None, ge=0)


class EventResponse(BaseModel):
    """Shape returned by GET /api/v1/events and POST /api/v1/events."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    venue_id: UUID
    name: str
    status: EventStatus
    expected_guest_count: int | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime
