"""Pydantic v2 request/response schemas for the events module.

Conventions:
- *Create schemas define what the CLIENT sends. No tenant_id, no id, no timestamps.
- *Update schemas for PATCH. ALL fields optional except version (required for
  optimistic locking per contract §4).
- *Response schemas define what the SERVER returns. Includes all public fields
  + computed fields (bars_count) + nested related entities (venue).
- model_config = {"from_attributes": True} lets us build schemas from ORM objects.
"""
from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.events.models import EventStatus


# ─── Venue re-export ──────────────────────────────────────────────────────────
from app.modules.venues.schemas import VenueResponse as VenueResponse  # noqa: F401


# ─── Event — Create ───────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    """Payload for POST /api/v1/events. Client-provided fields only.

    New events always start at status=draft (backend enforces, not client input).
    """
    name: str = Field(..., min_length=1, max_length=255)
    venue_id: UUID
    scheduled_at: datetime
    scheduled_end_at: datetime
    expected_guest_count: int | None = Field(default=None, ge=0)

    # Slesh-aligned fields (Phase B w1) — all optional
    stripe_ragione_sociale: str | None = Field(default=None, max_length=255)
    staff_arrival_time: time | None = None
    wristband_qty_per_type: dict | None = None
    topup_denominations_user: list[int] | None = None
    topup_denominations_staff: list[int] | None = None
    refund_min_credit_cents: int | None = Field(default=None, ge=0)
    refund_fee_cents: int | None = Field(default=None, ge=0)
    refund_window_open_at: datetime | None = None
    refund_window_close_at: datetime | None = None


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
    scheduled_at: datetime | None = None
    scheduled_end_at: datetime | None = None
    expected_guest_count: int | None = Field(default=None, ge=0)
    ended_at: datetime | None = None
    version: int = Field(..., ge=1)


# ─── Event — Response ─────────────────────────────────────────────────────────

class EventResponse(BaseModel):
    """Shape returned by every events endpoint.

    Includes:
      - Core fields (id, name, status, ...)
      - scheduled_at + scheduled_end_at (when the event runs)
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
    scheduled_at: datetime
    scheduled_end_at: datetime
    venue: VenueResponse
    expected_guest_count: int | None
    stripe_ragione_sociale: str | None
    staff_arrival_time: time | None
    wristband_qty_per_type: dict | None
    topup_denominations_user: list[int] | None
    topup_denominations_staff: list[int] | None
    refund_min_credit_cents: int | None
    refund_fee_cents: int | None
    refund_window_open_at: datetime | None
    refund_window_close_at: datetime | None
    bars_count: int
    version: int
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime
