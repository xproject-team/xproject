"""Pydantic v2 request/response schemas for the venues module.

Conventions: see app/modules/events/schemas.py docstring. Same principles
apply — Create schemas for client input, Response schemas for server output,
no ad-hoc JSON.
"""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VenueResponse(BaseModel):
    """Canonical Venue response. Used by GET /api/v1/venues AND embedded
    inside EventResponse.venue. tenant_id omitted — the viewing client
    is already scoped to its tenant by JWT, redundant to echo back.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    address: str | None = None
    capacity: int | None = None


class VenueCreate(BaseModel):
    """Payload for POST /api/v1/venues. Client-provided fields only."""
    name: str = Field(..., min_length=1, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    capacity: int | None = Field(default=None, ge=0)
