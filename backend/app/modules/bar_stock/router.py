"""HTTP router for the bar_stock module.

Endpoints:
    GET    /bar-stock/by-event/{event_id}         list stock for event (filter: bar_id)
    GET    /bar-stock/{id}                        single stock row
    POST   /bar-stock/allocate                    transfer IN (create or topup)
    POST   /bar-stock/{id}/consume                decrement current_qty
    POST   /bar-stock/{id}/return                 transfer OUT to warehouse
    POST   /bar-stock/{id}/adjust                 manual correction (audited)

URL design: listing is scoped by path (/by-event/{event_id}) following
the event_products pattern — stock always exists within an event.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.auth.access_guards import assert_bar_access, resolve_bar_filter
from app.modules.bar_stock.schemas import (
    AdjustRequest,
    AllocateRequest,
    BarStockResponse,
    ConsumeRequest,
    ReturnRequest,
)
from app.modules.bar_stock.service import (
    BarNotFoundError,
    BarNotInEventError,
    BarStockNotFoundError,
    BarStockService,
    EventNotFoundError,
    ExcessiveReturnError,
    InsufficientStockError,
    InvalidAdjustmentError,
    ProductArchivedError,
    ProductNotFoundError,
)


async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return current_user.tenant_id


router = APIRouter()


# ─── Read endpoints ───────────────────────────────────────────────────────────

@router.get(
    "/by-event/{event_id}",
    response_model=list[BarStockResponse],
)
async def list_stock_for_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    bar_id: Annotated[UUID | None, Query(description="Filter by bar")] = None,
) -> list[BarStockResponse]:
    """Return stock rows for an event, optionally scoped to a specific bar.

    Use cases:
    - Dashboard per-bar tiles: by-event/{event_id}?bar_id=X
    - Warehouse overview: by-event/{event_id} (all stock rows)
    - 404 if event doesn't exist (vs. silent empty list)
    """
    # Auto-fill bar_id for Manager/Bartender; assert access for everyone
    bar_id = resolve_bar_filter(current_user, bar_id)
    assert_bar_access(current_user, bar_id)
    service = BarStockService(db)
    try:
        rows = await service.list_for_event(current_user.tenant_id, event_id, bar_id=bar_id)
    except EventNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    return [BarStockResponse.model_validate(s) for s in rows]


@router.get("/{stock_id}", response_model=BarStockResponse)
async def get_stock(
    stock_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> BarStockResponse:
    """Fetch a single stock row."""
    service = BarStockService(db)
    try:
        stock = await service.get_stock(tenant_id, stock_id)
    except BarStockNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "bar_stock_not_found", "message": str(e)},
        )
    return BarStockResponse.model_validate(stock)


# ─── Allocate ─────────────────────────────────────────────────────────────────

@router.post(
    "/allocate",
    response_model=BarStockResponse,
    status_code=status.HTTP_201_CREATED,
)
async def allocate_stock(
    payload: AllocateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> BarStockResponse:
    """Transfer stock IN from warehouse. Create row OR top up if (event, bar, product) exists.

    Error responses:
    - 404 event_not_found / bar_not_found / product_not_found
    - 422 bar_not_in_event / product_archived
    """
    service = BarStockService(db)
    try:
        stock = await service.allocate(tenant_id, payload)
    except EventNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    except BarNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "bar_not_found", "message": str(e)},
        )
    except BarNotInEventError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "bar_not_in_event", "message": str(e)},
        )
    except ProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "product_not_found", "message": str(e)},
        )
    except ProductArchivedError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "product_archived", "message": str(e)},
        )
    return BarStockResponse.model_validate(stock)


# ─── Consume ──────────────────────────────────────────────────────────────────

@router.post("/{stock_id}/consume", response_model=BarStockResponse)
async def consume_stock(
    stock_id: UUID,
    payload: ConsumeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> BarStockResponse:
    """Decrement current_qty by the requested quantity.

    Error responses:
    - 404 bar_stock_not_found
    - 422 insufficient_stock (payload includes available + requested)
    """
    service = BarStockService(db)
    try:
        stock = await service.consume(tenant_id, stock_id, payload)
    except BarStockNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "bar_stock_not_found", "message": str(e)},
        )
    except InsufficientStockError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "insufficient_stock",
                "message": str(e),
                "available": e.available,
                "requested": e.requested,
            },
        )
    return BarStockResponse.model_validate(stock)


# ─── Return ───────────────────────────────────────────────────────────────────

@router.post("/{stock_id}/return", response_model=BarStockResponse)
async def return_stock(
    stock_id: UUID,
    payload: ReturnRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> BarStockResponse:
    """Transfer unused stock OUT to warehouse. Increments returned_qty
    (current_qty is unchanged — they're separate counters for reconciliation).

    Error responses:
    - 404 bar_stock_not_found
    - 422 excessive_return (payload includes max_returnable + requested)
    """
    service = BarStockService(db)
    try:
        stock = await service.return_stock(tenant_id, stock_id, payload)
    except BarStockNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "bar_stock_not_found", "message": str(e)},
        )
    except ExcessiveReturnError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "excessive_return",
                "message": str(e),
                "max_returnable": e.max_returnable,
                "requested": e.requested,
            },
        )
    return BarStockResponse.model_validate(stock)


# ─── Adjust ───────────────────────────────────────────────────────────────────

@router.post("/{stock_id}/adjust", response_model=BarStockResponse)
async def adjust_stock(
    stock_id: UUID,
    payload: AdjustRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> BarStockResponse:
    """Manual correction. Provide any/all of new_allocated/new_current/new_returned.
    Omitted fields keep their existing values.

    Error responses:
    - 404 bar_stock_not_found
    - 422 invalid_adjustment (payload includes violation tag)
    """
    service = BarStockService(db)
    try:
        stock = await service.adjust(tenant_id, stock_id, payload)
    except BarStockNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "bar_stock_not_found", "message": str(e)},
        )
    except InvalidAdjustmentError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_adjustment",
                "message": str(e),
                "violation": e.violation,
            },
        )
    return BarStockResponse.model_validate(stock)
