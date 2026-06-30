"""Pydantic v2 request/response schemas for the Warehouse module.

These schemas are the contract between the backend API and:
  - Frontend TanStack Query hooks (1:1 mapped to TS interfaces in
    features/warehouse/useWarehouse.ts)
  - The InvoiceService + ScanService + ReconciliationEngine (internal shapes)
  - Future consumers (Reports module, Dashboard integrations)

Field names MUST mirror the ORM model exactly; the frontend will define
TypeScript interfaces with the same names. Drift here breaks the
contract-first architecture that lets us swap backend patterns without
frontend rewrites.

Invoice reconciliation is the hero feature — see DiscrepancyReport at
the bottom of this file. Everything else (inventory, scans, allocations)
is supporting structure for that reconciliation loop.

Spec: docs/warehouse-module-spec.md §4 + §7.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ─── Enums (literal-typed for runtime + IDE safety) ───────────────────────────
# Mirror the Postgres enums declared in j1_add_warehouse.py migration.

InvoiceStatus = Literal[
    "EXPECTED",
    "SCANNING",
    "PAUSED",
    "VERIFIED",
    "DISCREPANCY",
    "DISPUTED",
    "CLOSED",
]

ScanType = Literal[
    "INTAKE",
    "DISPATCH",
    "RETURN",
    "ADJUSTMENT",
    "INSPECT",
    "CONSUMED",
]

ScannerRole = Literal["owner", "manager", "bartender", "warehouse_keeper"]

InvoiceLineKind = Literal["catalog_product", "miscellaneous"]

# For discrepancy reporting — one of 4 outcomes per line
DiscrepancyLineStatus = Literal["match", "short", "extra", "unexpected"]

# For reconciliation overall — rolls up the line statuses
OverallDiscrepancyStatus = Literal["match", "discrepancy", "dispute_opened"]


# ═════════════════════════════════════════════════════════════════════════════
# INVOICE SCHEMAS (the hero entity)
# ═════════════════════════════════════════════════════════════════════════════

class InvoiceItemBase(BaseModel):
    """One line item on a delivery invoice.

    Two shapes allowed (enforced by migration CHECK constraints):
      - kind='catalog_product' → product_id required, miscellaneous_description NULL
      - kind='miscellaneous'   → miscellaneous_description required, product_id NULL

    unit_price_cents is optional (Omar may not always record prices),
    but line_total_cents is auto-computed when both qty + unit_price exist.
    """
    kind: InvoiceLineKind = "catalog_product"
    product_id: UUID | None = None
    miscellaneous_description: str | None = None
    expected_qty: Decimal
    unit_price_cents: int | None = None

    @model_validator(mode="after")
    def validate_kind_consistency(self) -> InvoiceItemBase:
        """Enforce the same rule the DB CHECK does, at API layer for clearer errors."""
        if self.kind == "catalog_product":
            if self.product_id is None:
                raise ValueError("catalog_product line requires product_id")
            if self.miscellaneous_description is not None:
                raise ValueError(
                    "catalog_product line must not have miscellaneous_description"
                )
        elif self.kind == "miscellaneous":
            if not self.miscellaneous_description:
                raise ValueError(
                    "miscellaneous line requires miscellaneous_description"
                )
            if self.product_id is not None:
                raise ValueError("miscellaneous line must not have product_id")
        if self.expected_qty <= 0:
            raise ValueError("expected_qty must be > 0")
        if self.unit_price_cents is not None and self.unit_price_cents < 0:
            raise ValueError("unit_price_cents must be >= 0")
        return self


class InvoiceItemResponse(InvoiceItemBase):
    """Full item row as returned by the API."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_id: UUID
    line_total_cents: int | None = None
    created_at: datetime
    updated_at: datetime


class InvoiceCreate(BaseModel):
    """Body of POST /warehouse/invoices.

    Omar fills this out from the paper invoice BEFORE the truck arrives.
    Status is implicit: always starts at EXPECTED.
    """
    invoice_number: str | None = None
    supplier_name: str = Field(min_length=1, max_length=255)
    expected_arrival_date: date
    notes: str | None = None
    items: list[InvoiceItemBase] = Field(min_length=1)
    # When True (default for the upload-PDF flow), the service treats this
    # invoice as ALREADY ARRIVED: it creates products for any miscellaneous
    # items, bumps warehouse_inventory.current_qty for every line by
    # expected_qty, and flips the invoice status to CLOSED. Matches the
    # operator mental model: "the fattura arrives, the bottles are now in
    # the storeroom." Set False to preserve the old EXPECTED -> scan-in
    # workflow if you genuinely don't have the goods yet.
    auto_intake: bool = True

    @model_validator(mode="after")
    def validate_has_items(self) -> InvoiceCreate:
        if not self.items:
            raise ValueError("invoice must have at least one line item")
        return self


class InvoiceUpdate(BaseModel):
    """Body of PATCH /warehouse/invoices/{id}.

    Only allowed while status=EXPECTED (before scanning starts). Once scanning
    has begun, the invoice is effectively frozen — the truth it represents
    must match what was sent to the supplier.
    """
    invoice_number: str | None = None
    supplier_name: str | None = Field(default=None, min_length=1, max_length=255)
    expected_arrival_date: date | None = None
    notes: str | None = None
    # Line items edited via separate sub-endpoints (add/update/delete line)


class InvoiceResponse(BaseModel):
    """Full invoice detail with expanded items.

    Used by GET /warehouse/invoices/{id} and all state-transition endpoints.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    invoice_number: str | None
    supplier_name: str
    expected_arrival_date: date
    status: InvoiceStatus
    scan_started_at: datetime | None
    scan_closed_at: datetime | None
    closed_by: UUID | None
    notes: str | None
    items: list[InvoiceItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class InvoiceSummary(BaseModel):
    """Lightweight row for GET /warehouse/invoices list view.

    Denormalizes total_expected_cents + items_count so the pending-deliveries
    strip on the dashboard renders without N+1 queries.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_number: str | None
    supplier_name: str
    expected_arrival_date: date
    status: InvoiceStatus
    items_count: int
    total_expected_cents: int | None
    scan_started_at: datetime | None
    created_at: datetime


class InvoiceDisputeRequest(BaseModel):
    """Body of POST /warehouse/invoices/{id}/dispute — Owner formally challenges supplier."""
    reason: str = Field(min_length=1, max_length=1000)


# ═════════════════════════════════════════════════════════════════════════════
# SCAN SCHEMAS
# ═════════════════════════════════════════════════════════════════════════════

class ScanCreate(BaseModel):
    """Body of POST /warehouse/scans.

    The high-frequency endpoint — called on every camera detection OR every
    manual-entry submit. Stay lean; the router decorates with user context.

    Three variants in practice (backend validates consistency):
      - INTAKE:  invoice_id REQUIRED, event_id + bar_id NULL
      - DISPATCH/RETURN/CONSUMED: event_id + bar_id REQUIRED, invoice_id NULL
      - INSPECT: all context optional; no DB state change, scan still logged
      - ADJUSTMENT: Owner-only, freeform inventory correction
    """
    scan_type: ScanType
    # Identification — at least one of these is required (enforced in service layer)
    product_id: UUID | None = None
    barcode_raw: str | None = Field(default=None, max_length=255)
    qty: Decimal = Field(default=Decimal("1"), gt=0)
    # INTAKE linkage
    invoice_id: UUID | None = None
    # DISPATCH / RETURN / CONSUMED linkage
    event_id: UUID | None = None
    bar_id: UUID | None = None
    # Idempotency key — UUID generated client-side at scan-event time so
    # retries (network blip, double-tap, queue replay) collapse to one row.
    # Recommended for all clients; required-by-policy for new scanner pages.
    client_event_id: UUID | None = None

    @model_validator(mode="after")
    def validate_identification(self) -> ScanCreate:
        if self.product_id is None and not self.barcode_raw:
            raise ValueError(
                "scan must include either product_id (after barcode resolution) "
                "or barcode_raw (for backend resolution + audit)"
            )
        return self


class ScanResponse(BaseModel):
    """Full scan detail as returned by the API."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    scan_type: ScanType
    invoice_id: UUID | None
    product_id: UUID | None
    # Snapshot fields — fetched with the response for display convenience
    product_name: str | None = None
    barcode_raw: str | None
    qty: Decimal
    event_id: UUID | None
    bar_id: UUID | None
    bar_name: str | None = None
    is_unexpected: bool
    pending_review: bool
    scanned_by_user_id: UUID | None
    scanned_by_user_name: str | None = None
    scanned_by_role: ScannerRole
    scanned_at: datetime
    # Void state — set after Federico-style undo within 5min window.
    voided_at: datetime | None = None
    voided_by_user_id: UUID | None = None
    voided_by_user_name: str | None = None


class BarcodeResolveRequest(BaseModel):
    """Body of POST /warehouse/barcode/resolve.

    Given a raw barcode string (EAN, UPC, QR), return the matching product
    or 'unknown' so the scanner UI can show the product name before submitting
    the actual scan.
    """
    barcode: str = Field(min_length=1, max_length=255)


class BarcodeResolveResponse(BaseModel):
    """Response from barcode lookup.

    status='known'   → product_id + product_name populated
    status='unknown' → raw_barcode echoed back, user falls to manual entry
    """
    status: Literal["known", "unknown"]
    barcode: str
    product_id: UUID | None = None
    product_name: str | None = None


# ═════════════════════════════════════════════════════════════════════════════
# INVENTORY SCHEMAS (Owner dashboard)
# ═════════════════════════════════════════════════════════════════════════════

class InventoryRow(BaseModel):
    """One row in the Owner's product inventory grid.

    Joins warehouse_inventory + products + sum of active warehouse_allocations
    so the grid renders with all derived values pre-computed.
    """
    model_config = ConfigDict(from_attributes=True)

    product_id: UUID
    product_name: str
    category: str | None = None
    brand: str | None = None
    current_qty: Decimal
    allocated_qty: Decimal = Decimal("0")
    available_qty: Decimal      # current - allocated (never negative, clamped at 0)
    low_stock_threshold: Decimal | None = None
    is_at_risk: bool = False    # current_qty < threshold
    last_movement_at: datetime | None = None


class InventoryKpis(BaseModel):
    """GET /warehouse/inventory/kpis — powers the 4 KPI tiles on /warehouse.

    Per spec §3.4:
      1. total_items — distinct products with stock > 0
      2. products_at_risk — count where current_qty < threshold
      3. active_allocations — sum reserved_qty across live/upcoming events
      4. pending_reviews — unexpected scans + unresolved discrepancies
    """
    total_items: int
    total_quantity: Decimal
    products_at_risk: int
    active_allocations: Decimal
    pending_reviews: int


# ═════════════════════════════════════════════════════════════════════════════
# ALLOCATION SCHEMAS
# ═════════════════════════════════════════════════════════════════════════════

class AllocationUpsert(BaseModel):
    """One product's allocation for an event.

    Sent as an array to PATCH /warehouse/allocations/event/{event_id} —
    Owner updates multiple products' reservations atomically.
    """
    product_id: UUID
    reserved_qty: Decimal = Field(ge=0)


class AllocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    product_id: UUID
    product_name: str | None = None
    reserved_qty: Decimal
    dispatched_qty: Decimal
    remaining_qty: Decimal      # reserved - dispatched


# ═════════════════════════════════════════════════════════════════════════════
# DISCREPANCY REPORT (the moment of truth — spec §7)
# ═════════════════════════════════════════════════════════════════════════════

class DiscrepancyLine(BaseModel):
    """One line in the reconciliation report.

    status semantics:
      'match'      — scanned_qty == expected_qty exactly
      'short'      — scanned_qty < expected_qty (supplier owes you)
      'extra'      — scanned_qty > expected_qty but product IS on invoice
      'unexpected' — product NOT on invoice (pending review territory)
    """
    product_id: UUID | None      # NULL for miscellaneous lines
    product_name: str
    expected_qty: Decimal
    scanned_qty: Decimal
    delta: Decimal               # scanned - expected (negative = short)
    status: DiscrepancyLineStatus
    unit_price_cents: int | None
    value_delta_cents: int | None  # delta × unit_price


class DiscrepancyReport(BaseModel):
    """The full reconciliation — what Omar waves at the driver.

    Computed by ReconciliationEngine when invoice closes. Persisted as the
    final state of the invoice alongside its scan history.
    """
    invoice_id: UUID
    supplier_name: str
    computed_at: datetime
    lines: list[DiscrepancyLine]
    total_expected_cents: int | None
    total_scanned_value_cents: int | None
    total_delta_cents: int | None
    has_shortage: bool
    has_unexpected: bool
    overall_status: OverallDiscrepancyStatus


# ═════════════════════════════════════════════════════════════════════════════
# ACTIVITY FEED (Owner dashboard side panel)
# ═════════════════════════════════════════════════════════════════════════════

class ActivityFeedRow(BaseModel):
    """One row in the activity feed.

    Formatted for display: '14:32 · Intake · 12× Bombay Gin · Marco (warehouse keeper)'.
    Role badge uses scanned_by_role snapshot so historical rows are always truthful.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scan_type: ScanType
    product_name: str | None
    qty: Decimal
    scanned_by_user_name: str | None
    scanned_by_role: ScannerRole
    scanned_at: datetime
    is_unexpected: bool
    pending_review: bool
