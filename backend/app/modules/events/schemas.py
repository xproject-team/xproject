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

    # Food revenue partnership share (XProject-native, not Slesh): the owner
    # keeps this percent of food gross, the food company keeps the rest.
    # 0-100; NULL = 100 (no split).
    food_revenue_share_pct: int | None = Field(default=None, ge=0, le=100)


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
    food_revenue_share_pct: int | None = None
    bars_count: int
    version: int
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ─── Full Event Create (Phase D — Create Event wizard composite) ─────────────

from app.modules.products.models import (  # noqa: E402
    FoodType,
    ProductCategory,
    ProductType,
    ProductUnit,
)


class FullEventBar(BaseModel):
    """One bar in the composite payload (index-referenced by menu/allocations)."""
    name: str = Field(..., min_length=1, max_length=255)
    slesh_negozio_id: str | None = Field(default=None, max_length=128)
    bar_type: str = "drinks"
    device_count: int = Field(default=0, ge=0)
    slesh_category: str | None = Field(default=None, max_length=64)
    is_active: bool = True


class FullEventProductInput(BaseModel):
    """One product in the composite payload.

    Products are TENANT-GLOBAL: if an active product with the same name +
    product_type already exists, it is REUSED (menus rotate across Sundance
    events but overlap heavily — ACQUA exists once, forever).
    """
    name: str = Field(..., min_length=1, max_length=255)
    product_type: ProductType
    category: ProductCategory | None = None
    tier_rank: int | None = Field(default=None, ge=1, le=4)
    unit: ProductUnit
    default_price_cents: int | None = Field(default=None, ge=0)
    iva_pct: float | None = Field(default=None, ge=0, le=1)
    cauzione_cents: int | None = Field(default=None, ge=0)
    food_type: FoodType | None = None


class FullEventMenuItem(BaseModel):
    """Listini line: product (by index) sold at bar (by index) at an event price."""
    bar_index: int = Field(..., ge=0)
    product_index: int = Field(..., ge=0)
    price_cents: int = Field(..., ge=0)
    tier_rank_override: int | None = Field(default=None, ge=1, le=4)
    is_available: bool = True


class FullEventAllocation(BaseModel):
    """Starting stock: qty of product (by index) allocated to bar (by index)."""
    bar_index: int = Field(..., ge=0)
    product_index: int = Field(..., ge=0)
    qty: int = Field(..., ge=0)


class FullEventCreate(BaseModel):
    """POST /events/full — create a complete event in ONE transaction.

    Event + bars + products + menu (event_products) + starting allocations
    (bar_stock). All-or-nothing: any invalid item rejects the whole payload
    with a per-item error report; nothing is committed on failure.
    Indices in menu/allocations refer to positions in bars[]/products[].
    """
    event: EventCreate
    bars: list[FullEventBar] = Field(default_factory=list, max_length=100)
    products: list[FullEventProductInput] = Field(default_factory=list, max_length=500)
    menu: list[FullEventMenuItem] = Field(default_factory=list, max_length=2000)
    allocations: list[FullEventAllocation] = Field(default_factory=list, max_length=2000)


class FullEventItemError(BaseModel):
    """Validation failure for one item in a composite section."""
    section: str
    index: int
    error: str


class FullEventCreateResponse(BaseModel):
    """Result of a successful composite create."""
    event: EventResponse
    bars_created: int
    products_created: int
    products_reused: int
    menu_items_created: int
    allocations_created: int


class FullEventDetail(BaseModel):
    """GET /events/{event_id}/full — event in wizard-round-trippable shape.

    Mirrors FullEventCreate so the frontend can populate WizardState from
    the response and PUT the edited payload back. Indices in menu/
    allocations refer to positions in bars[]/products[].

    Ordering (contractual — do not change without frontend coordination):
      - bars:         created_at ASC, id ASC
      - products:     name ASC, id ASC
      - menu:         (bar_index, product_index) ASC
      - allocations:  (bar_index, product_index) ASC
    """
    event: EventResponse
    bars: list[FullEventBar]
    products: list[FullEventProductInput]
    menu: list[FullEventMenuItem]
    allocations: list[FullEventAllocation]
