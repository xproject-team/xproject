"""HTTP router for the event_storage module.

Endpoints under /api/v1/event-storage:

Master list (supplier_products):
    GET  /supplier-products[?category=X]    list all (with optional filter)
    POST /supplier-products                  Owner-only — create master item

Per-event stock (event_stock_items):
    GET    /items?event_id=X                 list rows for an event
    POST   /items/bulk?event_id=X            Owner-only — bulk upsert (idempotent)
    DELETE /items/{item_id}                  Owner-only — delete one
    GET    /summary?event_id=X               aggregation for warehouse/inventory

Permissions:
    Reads (GET) require authenticated user. Warehouse + Inventory pages
    are visible to managers as well as owners.
    Writes (POST/DELETE) require Owner. Wizard-time configuration is
    owner-only.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User, UserRole
from app.modules.auth.permissions import get_active_role
from app.modules.auth.router import get_current_user
from app.modules.events.models import Event
from app.modules.event_storage.schemas import (
    ActivityFeedRow,
    BarAllocationSummary,
    DispatchBulkCreate,
    DispatchCreate,
    DispatchResponse,
    EventStockItemBulkUpsert,
    EventStockItemResponse,
    StorageSummaryResponse,
    SupplierProductCreate,
    SupplierProductResponse,
)
from app.modules.event_storage.service import (
    BarNotFoundError,
    EventStockItemNotFoundError,
    EventStorageService,
    SupplierProductNotFoundError,
)


router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────

def _require_owner(current_user: User) -> None:
    if get_active_role(current_user) != UserRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "owner_only",
                "message": "Only the tenant Owner can modify event storage.",
            },
        )


async def _get_event_or_404(
    db: AsyncSession, tenant_id: UUID, event_id: UUID,
) -> Event:
    """Verify the event exists for this tenant — prevents cross-tenant
    writes and gives clean 404s instead of FK IntegrityErrors."""
    event = await db.get(Event, event_id)
    if event is None or event.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "event_not_found",
                "message": f"Event {event_id} not found in this tenant.",
            },
        )
    return event


# ─── Supplier products (master list) ──────────────────────────────────

@router.get(
    "/supplier-products",
    response_model=list[SupplierProductResponse],
)
async def list_supplier_products(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    category: str | None = Query(default=None, max_length=64),
) -> list[SupplierProductResponse]:
    """Master list — used by the wizard's autocomplete and the Warehouse
    page's "Browse catalog" view. Optional category filter narrows to
    one accordion section (gin, vodka, beer_keg, mixer, etc)."""
    service = EventStorageService(db)
    rows = await service.list_supplier_products(
        current_user.tenant_id, category=category,
    )
    return [SupplierProductResponse.model_validate(r) for r in rows]


@router.post(
    "/supplier-products",
    response_model=SupplierProductResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_supplier_product(
    payload: SupplierProductCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SupplierProductResponse:
    """Owner-only: add a new item to the master list. Used by the
    wizard's '+ Add new' inline action when Omar receives a product
    not yet in the catalog. Idempotent on (tenant_id, supplier_sku) —
    re-posting the same SKU refreshes last_unit_price_eur and returns
    the existing row."""
    _require_owner(current_user)
    service = EventStorageService(db)
    sp = await service.upsert_supplier_product(
        current_user.tenant_id,
        supplier_sku=payload.supplier_sku,
        item_name=payload.item_name,
        category=payload.category,
        default_unit=payload.default_unit,
        units_per_pack=payload.units_per_pack,
        volume_per_unit_ml=payload.volume_per_unit_ml,
        last_unit_price_eur=payload.last_unit_price_eur,
        supplier_name=payload.supplier_name,
    )
    await db.commit()
    await db.refresh(sp)
    return SupplierProductResponse.model_validate(sp)


# ─── Event stock items ────────────────────────────────────────────────

@router.get("/items", response_model=list[EventStockItemResponse])
async def list_event_stock_items(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    event_id: Annotated[UUID, Query(...)],
) -> list[EventStockItemResponse]:
    """List every stock item declared for the event. Used by the wizard
    to repopulate the table on re-open, and by the Inventory page."""
    await _get_event_or_404(db, current_user.tenant_id, event_id)
    service = EventStorageService(db)
    rows = await service.list_event_stock_items(current_user.tenant_id, event_id)
    return [EventStockItemResponse.model_validate(r) for r in rows]


@router.post(
    "/items/bulk",
    response_model=list[EventStockItemResponse],
)
async def bulk_upsert_event_stock_items(
    payload: EventStockItemBulkUpsert,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    event_id: Annotated[UUID, Query(...)],
) -> list[EventStockItemResponse]:
    """Owner-only: declare/update the full stock manifest for an event
    in one transaction. Idempotent on
    (tenant_id, event_id, supplier_product_id) — re-posting refreshes
    qtys instead of duplicating. As a side effect, each item's
    unit_price_eur refreshes the corresponding supplier_product's
    last_unit_price_eur.

    Errors:
      400 if any supplier_product_id is unknown / cross-tenant.
      404 if event doesn't exist in tenant.
      403 if caller is not Owner.
    """
    _require_owner(current_user)
    await _get_event_or_404(db, current_user.tenant_id, event_id)
    service = EventStorageService(db)
    try:
        rows = await service.bulk_upsert_event_stock_items(
            current_user.tenant_id, event_id, payload.items,
        )
    except SupplierProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "supplier_product_not_found",
                "message": f"supplier_product_id {e.supplier_product_id} "
                           "is unknown in this tenant",
            },
        )
    await db.commit()
    for r in rows:
        await db.refresh(r)
    return [EventStockItemResponse.model_validate(r) for r in rows]


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_event_stock_item(
    item_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Owner-only: remove a single stock row. Use bulk-upsert for
    quantity changes — DELETE is for items declared by mistake."""
    _require_owner(current_user)
    service = EventStorageService(db)
    try:
        await service.delete_event_stock_item(current_user.tenant_id, item_id)
    except EventStockItemNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "event_stock_item_not_found",
                "message": f"Stock item {e.item_id} not found in tenant",
            },
        )
    await db.commit()


# ─── Summary ──────────────────────────────────────────────────────────

@router.get("/summary", response_model=StorageSummaryResponse)
async def get_storage_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    event_id: Annotated[UUID, Query(...)],
) -> StorageSummaryResponse:
    """Aggregation for the Warehouse + Inventory pages. Returns total
    items received, by-category counts, total invoice value (when
    pricing data is present), and per-product row breakdown.

    Allocated / remaining figures arrive in Phase 2.1 once the
    supplier_product -> Slesh product mapping is established."""
    await _get_event_or_404(db, current_user.tenant_id, event_id)
    service = EventStorageService(db)
    return await service.get_storage_summary(current_user.tenant_id, event_id)


# ─── Dispatch (event_stock_bar_allocations) ───────────────────────────


@router.post(
    "/allocations",
    response_model=DispatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dispatch(
    event_id: Annotated[UUID, Query()],
    payload: DispatchCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DispatchResponse:
    """Dispatch N of one supplier_product to one bar. Owner-only.

    History-preserving — calling this twice with the same body creates
    two separate rows so the activity feed has full provenance.
    """
    _require_owner(current_user)
    await _get_event_or_404(db, current_user.tenant_id, event_id)

    svc = EventStorageService(db)
    try:
        row = await svc.create_dispatch(
            current_user.tenant_id, event_id, payload,
            dispatched_by_user_id=current_user.id,
        )
    except SupplierProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unknown_supplier_product",
                "supplier_product_id": str(e.supplier_product_id),
            },
        )
    except BarNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unknown_bar",
                "bar_id": str(e.bar_id),
            },
        )
    await db.commit()
    return DispatchResponse.model_validate(row)


@router.post(
    "/allocations/bulk",
    response_model=list[DispatchResponse],
    status_code=status.HTTP_201_CREATED,
)
async def bulk_create_dispatches(
    event_id: Annotated[UUID, Query()],
    payload: DispatchBulkCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[DispatchResponse]:
    """Atomic bulk dispatch. Owner-only. Any invalid id rolls back the
    entire batch."""
    _require_owner(current_user)
    await _get_event_or_404(db, current_user.tenant_id, event_id)

    svc = EventStorageService(db)
    try:
        rows = await svc.bulk_create_dispatches(
            current_user.tenant_id, event_id, payload.items,
            dispatched_by_user_id=current_user.id,
        )
    except SupplierProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unknown_supplier_product",
                "supplier_product_id": str(e.supplier_product_id),
            },
        )
    except BarNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unknown_bar",
                "bar_id": str(e.bar_id),
            },
        )
    await db.commit()
    return [DispatchResponse.model_validate(r) for r in rows]


@router.get("/activity", response_model=list[ActivityFeedRow])
async def list_activity_feed(
    event_id: Annotated[UUID, Query()],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityFeedRow]:
    """Recent dispatches for the Warehouse-page sidebar. Readable by
    any authenticated user in the tenant."""
    await _get_event_or_404(db, current_user.tenant_id, event_id)
    svc = EventStorageService(db)
    return await svc.list_activity_feed(
        current_user.tenant_id, event_id, limit=limit,
    )


@router.get("/by-bar", response_model=list[BarAllocationSummary])
async def list_bar_allocations(
    event_id: Annotated[UUID, Query()],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[BarAllocationSummary]:
    """Per-bar grouped totals for the Inventory page. Readable by any
    authenticated user."""
    await _get_event_or_404(db, current_user.tenant_id, event_id)
    svc = EventStorageService(db)
    return await svc.list_bar_allocations(current_user.tenant_id, event_id)

