"""Pydantic v2 request/response schemas for the events module.

Conventions:
- *Create schemas define what the CLIENT sends. No tenant_id, no id, no timestamps.
- *Update schemas for PATCH. ALL fields optional except version (required for
  optimistic locking per contract §4).
- *Response schemas define what the SERVER returns. Includes all public fields
  + computed fields (bars_count) + nested related entities (venue).
- model_config = {"from_attributes": True} lets us build schemas from ORM objects.
"""
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.events.models import EventStatus


# ─── Venue (read-only shape; full CRUD in a later phase) ──────────────────────

class VenueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    address: str | None = None
    capacity: int | None = None


# ─── Event — Create ───────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    """Payload for POST /api/v1/events. Client-provided fields only.

    New events always start at status=draft (backend enforces, not client input).
    """
    name: str = Field(..., min_length=1, max_length=255)
    venue_id: UUID
    scheduled_date: date
    expected_guest_count: int | None = Field(default=None, ge=0)


# ─── Event — Update (PATCH /events/{id}) ──────────────────────────────────────

class EventUpdate(BaseModel):
    """Payload for PATCH /api/v1/events/{id}.

    ALL mutable fields are optional (client sends only what is changing).
    `version` is REQUIRED — it is the current version the client holds;
    the service layer compares it against the DB version and returns 409
    Conflict if they differ. See contract §4 (optimistic locking).

    Note: `status` is NOT in this schema by design. Status transitions use
    dedicated endpoints (/activate, /start, /end). See contract §2.5.
    """
    name: str | None = Field(default=None, min_length=1, max_length=255)
    venue_id: UUID | None = None
    scheduled_date: date | None = None
    expected_guest_count: int | None = Field(default=None, ge=0)
    ended_at: datetime | None = None
    version: int = Field(..., ge=1)


# ─── Event — Response ─────────────────────────────────────────────────────────

class EventResponse(BaseModel):
    """Shape returned by every events endpoint.

    Includes:
      - Core fields (id, name, status, ...)
      - scheduled_date (when the event is planned)
      - Nested venue (so frontend can render venue.name without separate fetch)
      - bars_count (computed in service layer via COUNT query)
      - version (for the frontend to send back in next PATCH)
      - Timestamps (started_at = went Live, ended_at = went Completed, plus audit)
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    status: EventStatus
    scheduled_date: date
    venue: VenueResponse
    expected_guest_count: int | None
    bars_count: int
    version: int
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime
