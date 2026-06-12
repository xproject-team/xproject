"""Pydantic schemas for the event_storage API."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ─── SupplierProduct ──────────────────────────────────────────────────

class SupplierProductBase(BaseModel):
    supplier_name: str = "Partesa"
    supplier_sku: str = Field(..., max_length=64)
    item_name: str = Field(..., max_length=255)
    category: str = Field(..., max_length=64)
    default_unit: str = Field(..., max_length=16)
    units_per_pack: int = 1
    volume_per_unit_ml: int | None = None
    last_unit_price_eur: Decimal | None = None


class SupplierProductCreate(SupplierProductBase):
    pass


class SupplierProductUpdate(BaseModel):
    item_name: str | None = None
    category: str | None = None
    default_unit: str | None = None
    units_per_pack: int | None = None
    volume_per_unit_ml: int | None = None
    last_unit_price_eur: Decimal | None = None


class SupplierProductResponse(SupplierProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime


# ─── EventStockItem ───────────────────────────────────────────────────

class EventStockItemBase(BaseModel):
    supplier_product_id: UUID
    qty_received: Decimal
    unit: str = Field(..., max_length=16)
    unit_price_eur: Decimal | None = None
    discount_amount_eur: Decimal | None = None
    line_total_eur: Decimal | None = None
    vat_pct: int | None = 22
    invoice_number: str | None = None
    invoice_date: date | None = None
    notes: str | None = None


class EventStockItemCreate(EventStockItemBase):
    """One row in a bulk-upsert payload."""
    pass


class EventStockItemBulkUpsert(BaseModel):
    """Payload for POST /events/{id}/storage/bulk. Replaces or upserts
    the rows for an event in one transaction."""
    items: list[EventStockItemCreate]


class EventStockItemResponse(EventStockItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    event_id: UUID
    created_at: datetime
    updated_at: datetime


# ─── Aggregations ────────────────────────────────────────────────────

class StorageSummaryRow(BaseModel):
    """Per-product breakdown for the warehouse + inventory pages.

    v1: received only. The allocated_to_bars / remaining_in_warehouse
    fields require a supplier_product -> product mapping (recipes link
    sold products to ingredient stock). That mapping lands in Phase 2.1.
    """
    supplier_product_id: UUID
    item_name: str
    category: str
    unit: str
    qty_received: Decimal
    line_total_eur: Decimal | None = None


class StorageSummaryResponse(BaseModel):
    """GET /events/{id}/storage/summary."""
    event_id: UUID
    total_items: int
    total_line_value_eur: Decimal | None
    by_category: dict[str, int]          # category -> item count
    rows: list[StorageSummaryRow]
