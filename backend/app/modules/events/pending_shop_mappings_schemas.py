"""Schemas for the phantom-bar defensive fix endpoints (Jul-19 sprint):

    GET  /events/{event_id}/pending-shop-mappings
    POST /events/{event_id}/pending-shop-mappings/{pending_id}/resolve
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PendingShopMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    slesh_shop_id: str
    first_seen_at: datetime
    order_count: int
    total_gross_cents: int
    sample_operator_email: str | None


class PendingShopMappingListResponse(BaseModel):
    items: list[PendingShopMappingResponse]
    total: int


class ResolvePendingShopMappingRequest(BaseModel):
    bar_id: UUID


class ResolvePendingShopMappingResponse(BaseModel):
    pending_id: UUID
    bar_id: UUID
    orders_replayed: int
    lines_replayed: int
