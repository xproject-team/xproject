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
BarType = Literal["drinks", "food", "mixed", "merch", "service"]


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
    device_count: int = 0
    slesh_category: str | None = None
    is_active: bool
    auto_created: bool = False


class BarCreate(BaseModel):
    """Payload for POST /api/v1/bars. Client provides event to attach to."""
    event_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    slesh_negozio_id: str | None = Field(default=None, max_length=128)
    bar_type: BarType = "drinks"
    device_count: int = Field(default=0, ge=0)
    slesh_category: str | None = Field(default=None, max_length=64)
    is_active: bool = True


class BarUpdate(BaseModel):
    """Payload for PATCH /api/v1/bars/{id}. All fields optional.

    event_id is NOT patchable — moving a bar between events would break
    transaction history. Delete and recreate if needed.
    """
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slesh_negozio_id: str | None = Field(default=None, max_length=128)
    bar_type: BarType | None = None
    device_count: int | None = Field(default=None, ge=0)
    slesh_category: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None


class StubBarKpi(BaseModel):
    """A live auto-created stub bar with the signals needed to render the
    dashboard name-picker dropdown.

    A stub is a Bar row the ingester minted for an unmapped Slesh shop_id;
    its identity (slesh_negozio_id, id) is locked from the first sale and
    survives the entire event, but its name is a placeholder until the
    owner picks one from the wizard-defined empty bars.

    `sales_count` is the total parent stock_transactions attributed to
    this bar — used to rank stubs against empty wizard bars (highest
    sales × highest device_count) for the (suggested) tag.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    name: str
    slesh_negozio_id: str
    bar_type: str
    device_count: int = 0
    slesh_category: str | None = None
    is_active: bool
    auto_created: bool = True
    sales_count: int
    suggested_target_bar_id: UUID | None = None


class BarMappingState(BaseModel):
    """Three-region view of an event's bars for the dashboard.

    - `empty_bars`:  wizard-defined bars with no Slesh shop_id yet (awaiting
                     first transaction). Sorted by device_count desc, so
                     the "biggest" empty appears first.
    - `stubs`:       auto-created bars bound to a Slesh shop_id but not yet
                     named by the owner. Sorted by sales_count desc.
                     Each carries a `suggested_target_bar_id` — the highest-
                     device-count empty wizard bar of the same bar_type
                     paired by rank.
    - `mapped_bars`: fully resolved bars (shop_id bound + name set). Normal
                     dashboard cards. Sorted alphabetically.
    """
    empty_bars:  list[BarResponse]
    stubs:       list[StubBarKpi]
    mapped_bars: list[BarResponse]
