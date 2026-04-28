"""HTTP router for the Warehouse module.

Owner + role-gated endpoints. Mounted at /api/v1/warehouse in app/main.py.

Endpoint groups (spec S8):
  /invoices                 — invoice lifecycle + state transitions
  /scans                    — the hot path + pending-review workflow
  /inventory                — read views for dashboard (KPIs, grid, feed)
  /allocations              — event reservations against warehouse stock
  /barcode/resolve          — lookup before scan submit

Role enforcement:
  - Owner-only endpoints: require_owner dependency (KPIs, dispute, approve/
    reject pending, ADJUSTMENT scans)
  - Warehouse + Owner: require_warehouse_or_owner (invoice management,
    intake/dispatch/return scans)
  - Role-aware (via service layer): /scans submit — the service enforces
    the spec S3.5 role-to-scan-type matrix at the business-logic level

Contract reference: §1.1 (4-layer architecture), router owns:
  - HTTP dependency injection (tenant, user, role)
  - Input validation via Pydantic request bodies
  - Status code mapping from domain exceptions
  - Response envelope construction (list/detail helpers below)

Spec: docs/warehouse-module-spec.md S8.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User, UserRole
from app.modules.auth.router import get_current_user
from app.modules.warehouse.inventory_service import InventoryService
from app.modules.warehouse.invoice_service import (
    InvalidInvoiceTransitionError,
    InvoiceNotEditableError,
    InvoiceNotFoundError,
    InvoiceService,
)
from app.modules.warehouse.scan_service import (
    AllocationNotFoundError,
    InvoiceNotActiveError,
    ScanPermissionError,
    ScanService,
    ScanValidationError,
)
from app.modules.warehouse.schemas import (
    ActivityFeedRow,
    AllocationResponse,
    AllocationUpsert,
    BarcodeResolveRequest,
    BarcodeResolveResponse,
    DiscrepancyReport,
    InventoryKpis,
    InventoryRow,
    InvoiceCreate,
    InvoiceDisputeRequest,
    InvoiceResponse,
    InvoiceStatus,
    InvoiceSummary,
    InvoiceUpdate,
    ScanCreate,
    ScanResponse,
)


# ─── Auth dependencies ────────────────────────────────────────────────────────

def require_owner(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Gate: Owner only. Used for dashboard KPIs, disputes, approvals,
    and ADJUSTMENT scans.
    """
    if current_user.role != UserRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "owner_only",
                "message": "Only the tenant Owner can access this endpoint.",
            },
        )
    return current_user


def require_owner_or_warehouse(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Gate: Owner OR Warehouse keeper.

    Used for warehouse READ endpoints (inventory grid, KPIs, activity feed,
    event allocations) and operational scan endpoints. Both roles need to
    see warehouse state to do their jobs:
      - Owner: full operational visibility + admin actions
      - Warehouse keeper: their primary surface; can't work without it

    Note: this guard is intentionally loose for visibility. Action endpoints
    that should be Owner-only (approve/reject pending review, dispute, archive)
    keep using require_owner above.
    """
    if current_user.role not in (UserRole.OWNER, UserRole.WAREHOUSE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "owner_or_warehouse_only",
                "message": "Only the tenant Owner or Warehouse keepers can access this endpoint.",
            },
        )
    return current_user


def require_warehouse_or_owner(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Gate: Owner OR warehouse_keeper role.

    Used for invoice management + write-path scan endpoints. Managers and
    bartenders go through scan-type-level enforcement in ScanService
    (spec S3.5 matrix).
    """
    # Normalize the role to lowercase string for robust comparison
    role_value = (
        current_user.role.value
        if hasattr(current_user.role, "value")
        else str(current_user.role)
    ).lower()
    if role_value not in ("owner", "warehouse_keeper"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "forbidden",
                "message": "Only Owner or warehouse keeper can perform this action.",
            },
        )
    return current_user


router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# INVENTORY — dashboard read endpoints (ordered FIRST to avoid path collision
# with /invoices/{id} when e.g. '/kpis' would collide)
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/inventory/kpis", response_model=InventoryKpis)
async def get_kpis(
    current_user: Annotated[User, Depends(require_owner_or_warehouse)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InventoryKpis:
    """5-metric dashboard header: total items, total qty, at-risk count,
    active allocations, pending reviews.
    """
    svc = InventoryService(db)
    return await svc.get_kpis(current_user.tenant_id)


@router.get("/inventory", response_model=list[InventoryRow])
async def get_inventory_grid(
    current_user: Annotated[User, Depends(require_owner_or_warehouse)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[InventoryRow]:
    """Product grid: per-product current/allocated/available + risk flag."""
    svc = InventoryService(db)
    return await svc.get_inventory_grid(current_user.tenant_id)


@router.get("/inventory/activity", response_model=list[ActivityFeedRow])
async def get_activity_feed(
    current_user: Annotated[User, Depends(require_owner_or_warehouse)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ActivityFeedRow]:
    """Last N scan events for the activity feed side panel."""
    svc = InventoryService(db)
    scans = await svc.get_activity_feed(current_user.tenant_id, limit=limit)
    return [_activity_row_from_scan(s) for s in scans]


@router.get("/inventory/pending-review", response_model=list[ScanResponse])
async def get_pending_review_queue(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ScanResponse]:
    """Owner's unexpected-scans queue awaiting approval or rejection."""
    svc = InventoryService(db)
    scans = await svc.get_pending_review_queue(current_user.tenant_id)
    return [_scan_response_from_orm(s) for s in scans]


# ═════════════════════════════════════════════════════════════════════════════
# BARCODE RESOLUTION — shared helper before submitting a scan
# ═════════════════════════════════════════════════════════════════════════════

@router.post("/barcode/resolve", response_model=BarcodeResolveResponse)
async def resolve_barcode(
    body: BarcodeResolveRequest,
    current_user: Annotated[User, Depends(get_current_user)],  # any role
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BarcodeResolveResponse:
    """Look up a barcode against the product catalog. Called by the scanner
    UI before submit to give immediate product-name feedback.
    """
    svc = ScanService(db)
    return await svc.resolve_barcode(current_user.tenant_id, body.barcode)


# ═════════════════════════════════════════════════════════════════════════════
# INVOICES — lifecycle + state transitions
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/invoices", response_model=list[InvoiceSummary])
async def list_invoices(
    current_user: Annotated[User, Depends(require_warehouse_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[InvoiceStatus | None, Query(alias="status")] = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[InvoiceSummary]:
    """Invoice list view. Filter by status (EXPECTED for pending-deliveries strip)."""
    svc = InvoiceService(db)
    invoices = await svc.list_invoices(
        current_user.tenant_id,
        status=status_filter,
        limit=limit,
    )
    return [_summary_from_invoice(i) for i in invoices]


@router.get("/invoices/pending", response_model=list[InvoiceSummary])
async def list_pending_deliveries(
    current_user: Annotated[User, Depends(require_warehouse_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[InvoiceSummary]:
    """Dashboard strip: EXPECTED/SCANNING/PAUSED, soonest first."""
    svc = InvoiceService(db)
    invoices = await svc.list_pending_deliveries(current_user.tenant_id)
    return [_summary_from_invoice(i) for i in invoices]


@router.post(
    "/invoices",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invoice(
    body: InvoiceCreate,
    current_user: Annotated[User, Depends(require_warehouse_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InvoiceResponse:
    """Create a new EXPECTED invoice with its line items atomically."""
    svc = InvoiceService(db)
    invoice = await svc.create_invoice(current_user.tenant_id, body)
    return _response_from_invoice(invoice)


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: UUID,
    current_user: Annotated[User, Depends(require_warehouse_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InvoiceResponse:
    """Full invoice detail with items."""
    svc = InvoiceService(db)
    try:
        invoice = await svc.get_invoice(current_user.tenant_id, invoice_id)
    except InvoiceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invoice_not_found", "message": str(e)},
        )
    return _response_from_invoice(invoice)


@router.patch("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: UUID,
    body: InvoiceUpdate,
    current_user: Annotated[User, Depends(require_warehouse_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InvoiceResponse:
    """Edit invoice header. Only allowed while status=EXPECTED."""
    svc = InvoiceService(db)
    try:
        invoice = await svc.update_invoice(current_user.tenant_id, invoice_id, body)
    except InvoiceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invoice_not_found", "message": str(e)},
        )
    except InvoiceNotEditableError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "invoice_not_editable", "message": str(e)},
        )
    return _response_from_invoice(invoice)


@router.post(
    "/invoices/{invoice_id}/start-scan",
    response_model=InvoiceResponse,
)
async def start_scan(
    invoice_id: UUID,
    current_user: Annotated[User, Depends(require_warehouse_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InvoiceResponse:
    """EXPECTED -> SCANNING. First scan against this invoice."""
    return await _transition(
        InvoiceService(db).start_scan,
        current_user.tenant_id,
        invoice_id,
    )


@router.post(
    "/invoices/{invoice_id}/pause",
    response_model=InvoiceResponse,
)
async def pause_scan(
    invoice_id: UUID,
    current_user: Annotated[User, Depends(require_warehouse_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InvoiceResponse:
    """SCANNING -> PAUSED. Session paused, resume later."""
    return await _transition(
        InvoiceService(db).pause_scan,
        current_user.tenant_id,
        invoice_id,
    )


@router.post(
    "/invoices/{invoice_id}/resume",
    response_model=InvoiceResponse,
)
async def resume_scan(
    invoice_id: UUID,
    current_user: Annotated[User, Depends(require_warehouse_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InvoiceResponse:
    """PAUSED -> SCANNING."""
    return await _transition(
        InvoiceService(db).resume_scan,
        current_user.tenant_id,
        invoice_id,
    )


@router.post(
    "/invoices/{invoice_id}/close",
    response_model=DiscrepancyReport,
)
async def close_scan(
    invoice_id: UUID,
    current_user: Annotated[User, Depends(require_warehouse_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DiscrepancyReport:
    """The moment of truth: run reconciliation + transition to VERIFIED
    or DISCREPANCY. Returns the DiscrepancyReport (Omar's fraud evidence).
    """
    svc = InvoiceService(db)
    try:
        _, report = await svc.close_scan(
            current_user.tenant_id,
            invoice_id,
            closed_by=current_user.id,
        )
    except InvoiceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invoice_not_found", "message": str(e)},
        )
    except InvalidInvoiceTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "invalid_transition", "message": str(e)},
        )
    return report


@router.get(
    "/invoices/{invoice_id}/report",
    response_model=DiscrepancyReport,
)
async def get_report(
    invoice_id: UUID,
    current_user: Annotated[User, Depends(require_warehouse_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DiscrepancyReport:
    """Return the DiscrepancyReport at ANY invoice state (including live
    during SCANNING). No state mutation — pure read + compute.
    """
    svc = InvoiceService(db)
    try:
        return await svc.compute_report(current_user.tenant_id, invoice_id)
    except InvoiceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invoice_not_found", "message": str(e)},
        )


@router.post(
    "/invoices/{invoice_id}/dispute",
    response_model=InvoiceResponse,
)
async def open_dispute(
    invoice_id: UUID,
    body: InvoiceDisputeRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InvoiceResponse:
    """Owner formally disputes a DISCREPANCY invoice. Reason is appended
    to the invoice notes with a timestamp.
    """
    svc = InvoiceService(db)
    try:
        invoice = await svc.open_dispute(
            current_user.tenant_id, invoice_id, body.reason
        )
    except InvoiceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invoice_not_found", "message": str(e)},
        )
    except InvalidInvoiceTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "invalid_transition", "message": str(e)},
        )
    return _response_from_invoice(invoice)


@router.post(
    "/invoices/{invoice_id}/archive",
    response_model=InvoiceResponse,
)
async def archive_invoice(
    invoice_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InvoiceResponse:
    """Terminal transition to CLOSED. From VERIFIED/DISCREPANCY/DISPUTED."""
    return await _transition(
        InvoiceService(db).archive,
        current_user.tenant_id,
        invoice_id,
    )


# ═════════════════════════════════════════════════════════════════════════════
# SCANS — the hot path + pending-review workflow
# ═════════════════════════════════════════════════════════════════════════════

@router.post(
    "/scans",
    response_model=ScanResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_scan(
    body: ScanCreate,
    current_user: Annotated[User, Depends(get_current_user)],  # service enforces role
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScanResponse:
    """Record a scan and apply its side effects.

    Role enforcement happens inside ScanService — spec S3.5 matrix decides
    whether this role can perform this scan_type (403 if not allowed).
    """
    svc = ScanService(db)
    role_value = (
        current_user.role.value
        if hasattr(current_user.role, "value")
        else str(current_user.role)
    ).lower()

    try:
        scan = await svc.submit_scan(
            current_user.tenant_id,
            body,
            scanned_by_user_id=current_user.id,
            scanned_by_role=role_value,
        )
    except ScanPermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "scan_permission_denied", "message": str(e)},
        )
    except ScanValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "scan_validation", "message": str(e)},
        )
    except InvoiceNotActiveError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "invoice_not_active", "message": str(e)},
        )
    except AllocationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "allocation_not_found", "message": str(e)},
        )
    return _scan_response_from_orm(scan)


@router.post(
    "/scans/{scan_id}/approve",
    response_model=ScanResponse,
)
async def approve_pending_scan(
    scan_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScanResponse:
    """Owner approves an unexpected scan — keep the inventory delta, clear flag."""
    svc = ScanService(db)
    try:
        scan = await svc.approve_pending(current_user.tenant_id, scan_id)
    except ScanValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "scan_not_pending", "message": str(e)},
        )
    return _scan_response_from_orm(scan)


@router.post(
    "/scans/{scan_id}/reject",
    response_model=ScanResponse,
)
async def reject_pending_scan(
    scan_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScanResponse:
    """Owner rejects — reverse the inventory delta, clear the flag."""
    svc = ScanService(db)
    try:
        scan = await svc.reject_pending(current_user.tenant_id, scan_id)
    except ScanValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "scan_not_pending", "message": str(e)},
        )
    return _scan_response_from_orm(scan)


# ═════════════════════════════════════════════════════════════════════════════
# ALLOCATIONS — event reservations against warehouse stock
# ═════════════════════════════════════════════════════════════════════════════

@router.get(
    "/allocations/event/{event_id}",
    response_model=list[AllocationResponse],
)
async def list_event_allocations(
    event_id: UUID,
    current_user: Annotated[User, Depends(require_owner_or_warehouse)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AllocationResponse]:
    """All warehouse reservations for one event."""
    # Use AllocationRepository directly — this is a simple read
    from app.modules.warehouse.repository import AllocationRepository
    repo = AllocationRepository(db)
    rows = await repo.list_for_event(current_user.tenant_id, event_id)
    return [
        AllocationResponse(
            id=alloc.id,
            event_id=alloc.event_id,
            product_id=alloc.product_id,
            product_name=product.name,
            reserved_qty=alloc.reserved_qty,
            dispatched_qty=alloc.dispatched_qty,
            remaining_qty=alloc.reserved_qty - alloc.dispatched_qty,
        )
        for alloc, product in rows
    ]


@router.patch(
    "/allocations/event/{event_id}",
    response_model=list[AllocationResponse],
)
async def upsert_event_allocations(
    event_id: UUID,
    body: list[AllocationUpsert],
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AllocationResponse]:
    """Owner updates multiple product allocations for an event atomically."""
    from app.modules.warehouse.repository import AllocationRepository
    repo = AllocationRepository(db)
    for item in body:
        await repo.upsert_reservation(
            current_user.tenant_id,
            event_id,
            item.product_id,
            item.reserved_qty,
        )
    await db.commit()
    # Re-fetch with product names for response
    rows = await repo.list_for_event(current_user.tenant_id, event_id)
    return [
        AllocationResponse(
            id=alloc.id,
            event_id=alloc.event_id,
            product_id=alloc.product_id,
            product_name=product.name,
            reserved_qty=alloc.reserved_qty,
            dispatched_qty=alloc.dispatched_qty,
            remaining_qty=alloc.reserved_qty - alloc.dispatched_qty,
        )
        for alloc, product in rows
    ]


# ═════════════════════════════════════════════════════════════════════════════
# Private helpers — ORM row → response envelope converters
# ═════════════════════════════════════════════════════════════════════════════

async def _transition(method, tenant_id: UUID, invoice_id: UUID) -> InvoiceResponse:
    """Shared wrapper for the simple transition endpoints (start/pause/resume/archive).

    Maps the common exception set into correct HTTP codes.
    """
    try:
        invoice = await method(tenant_id, invoice_id)
    except InvoiceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invoice_not_found", "message": str(e)},
        )
    except InvalidInvoiceTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "invalid_transition", "message": str(e)},
        )
    return _response_from_invoice(invoice)


def _response_from_invoice(invoice) -> InvoiceResponse:
    """ORM DeliveryInvoice → InvoiceResponse Pydantic model."""
    from app.modules.warehouse.schemas import InvoiceItemResponse
    items = [
        InvoiceItemResponse.model_validate(it, from_attributes=True)
        for it in (invoice.items or [])
    ]
    return InvoiceResponse(
        id=invoice.id,
        tenant_id=invoice.tenant_id,
        invoice_number=invoice.invoice_number,
        supplier_name=invoice.supplier_name,
        expected_arrival_date=invoice.expected_arrival_date,
        status=invoice.status,
        scan_started_at=invoice.scan_started_at,
        scan_closed_at=invoice.scan_closed_at,
        closed_by=invoice.closed_by,
        notes=invoice.notes,
        items=items,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
    )


def _summary_from_invoice(invoice) -> InvoiceSummary:
    """Lightweight InvoiceSummary for list endpoints."""
    items_count = len(invoice.items or [])
    total = None
    for it in (invoice.items or []):
        if it.line_total_cents is not None:
            total = (total or 0) + it.line_total_cents
    return InvoiceSummary(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        supplier_name=invoice.supplier_name,
        expected_arrival_date=invoice.expected_arrival_date,
        status=invoice.status,
        items_count=items_count,
        total_expected_cents=total,
        scan_started_at=invoice.scan_started_at,
        created_at=invoice.created_at,
    )


def _scan_response_from_orm(scan) -> ScanResponse:
    """WarehouseScan → ScanResponse with name fields populated."""
    product = getattr(scan, "product", None)
    bar = getattr(scan, "bar", None)
    user = getattr(scan, "scanned_by", None)
    return ScanResponse(
        id=scan.id,
        tenant_id=scan.tenant_id,
        scan_type=scan.scan_type,
        invoice_id=scan.invoice_id,
        product_id=scan.product_id,
        product_name=product.name if product is not None else None,
        barcode_raw=scan.barcode_raw,
        qty=scan.qty,
        event_id=scan.event_id,
        bar_id=scan.bar_id,
        bar_name=bar.name if bar is not None else None,
        is_unexpected=scan.is_unexpected,
        pending_review=scan.pending_review,
        scanned_by_user_id=scan.scanned_by_user_id,
        scanned_by_user_name=getattr(user, "full_name", None) if user else None,
        scanned_by_role=scan.scanned_by_role,
        scanned_at=scan.scanned_at,
    )


def _activity_row_from_scan(scan) -> ActivityFeedRow:
    """WarehouseScan → ActivityFeedRow for the side-panel feed."""
    product = getattr(scan, "product", None)
    user = getattr(scan, "scanned_by", None)
    return ActivityFeedRow(
        id=scan.id,
        scan_type=scan.scan_type,
        product_name=product.name if product is not None else None,
        qty=scan.qty,
        scanned_by_user_name=getattr(user, "full_name", None) if user else None,
        scanned_by_role=scan.scanned_by_role,
        scanned_at=scan.scanned_at,
        is_unexpected=scan.is_unexpected,
        pending_review=scan.pending_review,
    )
