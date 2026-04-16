"""Pydantic v2 request/response schemas for the bars module.

Follows the same conventions as app/modules/events/schemas.py —
Create/Update schemas for client input, Response schemas for server output.

Note: bar_type is a string (not enum) matching the underlying model,
which uses String(32) for forward compatibility with future bar types.
Validated at the schema layer to the known set of values.
"""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# The canonical set of bar_type values. Extend here when new types are added.
BarType = Literal["drinks", "food", "mixed"]


class BarResponse(BaseModel):
    """Shape returned by GET /api/v1/bars and GET /api/v1/bars/{id}.

    tenant_id omitted — client is already scoped to its tenant by JWT,
    redundant to echo back (same pattern as VenueResponse).
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    name: str
    slesh_negozio_id: str | None = None
    bar_type: str
    is_active: bool


class BarCreate(BaseModel):
    """Payload for POST /api/v1/bars. Client provides event to attach to."""
    event_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    slesh_negozio_id: str | None = Field(default=None, max_length=128)
    bar_type: BarType = "drinks"
    is_active: bool = True


class BarUpdate(BaseModel):
    """Payload for PATCH /api/v1/bars/{id}. All fields optional.

    event_id is NOT patchable — moving a bar between events would break
    transaction history. Delete and recreate if needed.
    """
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slesh_negozio_id: str | None = Field(default=None, max_length=128)
    bar_type: BarType | None = None
    is_active: bool | None = None
