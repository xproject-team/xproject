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

    qty_received  = total declared in event_stock_items
    qty_allocated = SUM(event_stock_bar_allocations.qty_allocated)
                    across all bars for this (event, supplier_product)
    qty_available = qty_received - qty_allocated  (warehouse remaining)

    These are DECLARATIVE totals only. Real-time consumption (sales
    depleting bar_stock) is tracked separately via the existing
    stock_transactions / burn-rate path and is NOT subtracted here.
    """
    supplier_product_id: UUID
    item_name: str
    category: str
    unit: str
    qty_received: Decimal
    qty_allocated: Decimal
    qty_available: Decimal
    line_total_eur: Decimal | None = None


class StorageSummaryResponse(BaseModel):
    """GET /event-storage/summary?event_id=X — aggregation for the
    Warehouse + Inventory pages.
    """
    event_id: UUID
    total_items: int                     # COUNT(DISTINCT supplier_product)
    total_qty_received: Decimal
    total_qty_allocated: Decimal
    total_line_value_eur: Decimal | None
    by_category: dict[str, int]          # category -> item count
    rows: list[StorageSummaryRow]


# ─── Dispatch (event_stock_bar_allocations) ───────────────────────────

class DispatchCreate(BaseModel):
    """Payload for POST /event-storage/allocations?event_id=X.

    One row = one dispatch event. To send 100 of A and 50 of B to the
    same bar, post two separate DispatchCreate items (or one bulk array;
    see DispatchBulkCreate below). History-preserving — re-posting the
    same payload creates a NEW row, not an upsert.
    """
    supplier_product_id: UUID
    bar_id: UUID
    qty_allocated: Decimal = Field(..., gt=0)
    notes: str | None = None


class DispatchBulkCreate(BaseModel):
    """Bulk payload — Omar dispatches multiple items in one click."""
    items: list[DispatchCreate]


class DispatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    event_id: UUID
    supplier_product_id: UUID
    bar_id: UUID
    qty_allocated: Decimal
    dispatched_by_user_id: UUID | None
    notes: str | None
    created_at: datetime         # serves as dispatched_at
    updated_at: datetime


class ActivityFeedRow(BaseModel):
    """One row in the Warehouse-page activity feed sidebar. Denormalises
    item + bar + user names so the frontend can render in one pass.
    """
    id: UUID
    qty_allocated: Decimal
    item_name: str
    item_unit: str               # supplier_product.default_unit
    bar_name: str
    user_name: str | None
    user_role: str | None
    dispatched_at: datetime


class BarAllocationSummary(BaseModel):
    """Per-bar totals — used by the Inventory page to show what each
    bar has been dispatched so far before Omar adds more."""
    bar_id: UUID
    bar_name: str
    items: list["BarAllocationItem"]


class BarAllocationItem(BaseModel):
    supplier_product_id: UUID
    item_name: str
    unit: str
    qty_total_allocated: Decimal

