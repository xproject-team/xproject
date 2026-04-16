"""Pydantic v2 request/response schemas for the event_products module.

Conventions:
- Response includes derived effective_tier_rank field (override OR product's default)
- Create requires event_id + bar_id + product_id + price_cents
- Update allows patching price, tier_rank_override, is_available
  (event/bar/product FKs NOT patchable — would corrupt analytics chain)

Field naming:
- tier_rank_override: client-provided override (null = inherit from Product)
- effective_tier_rank: computed field on Response (the ACTUAL tier_rank used
  for analytics) — requires service to compute via join with Product
"""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EventProductResponse(BaseModel):
    """Shape returned by GET endpoints.

    effective_tier_rank is computed by the service — it's the override
    if set, otherwise the underlying Product's tier_rank. Clients (Dashboard,
    analytics) should use THIS field for aggregations, not tier_rank_override.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    bar_id: UUID
    product_id: UUID
    price_cents: int = Field(..., ge=0)
    tier_rank_override: int | None = Field(default=None, ge=1, le=4)
    effective_tier_rank: int | None = Field(
        default=None, ge=1, le=4,
        description="tier_rank_override if set, else Product.tier_rank",
    )
    is_available: bool


class EventProductCreate(BaseModel):
    """Payload for POST /api/v1/event-products.

    Rules enforced in service:
    - event must exist in tenant
    - bar must exist AND belong to the same event (not a bar from a different event)
    - product must exist, be active (not archived), and belong to tenant
    - (event_id, bar_id, product_id) triple must not already exist
    """
    event_id: UUID
    bar_id: UUID
    product_id: UUID
    price_cents: int = Field(..., ge=0)
    tier_rank_override: int | None = Field(default=None, ge=1, le=4)
    is_available: bool = True


class EventProductUpdate(BaseModel):
    """Payload for PATCH /api/v1/event-products/{id}. All fields optional.

    NOT patchable:
    - event_id / bar_id / product_id (structural identity; delete + recreate
      if a menu line needs to change which product/bar it points to, to keep
      transaction history and analytics coherent)
    """
    price_cents: int | None = Field(default=None, ge=0)
    tier_rank_override: int | None = Field(default=None, ge=1, le=4)
    is_available: bool | None = None
