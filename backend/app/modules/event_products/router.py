"""HTTP router for the event_products module.

Endpoints:
    GET    /event-products/by-event/{event_id}   list menu for an event
                                                  (filters: bar_id, only_available)
    GET    /event-products/{id}                   single menu item
    POST   /event-products                        add product to an event's menu
    PATCH  /event-products/{id}                   update price/tier/availability
    DELETE /event-products/{id}                   remove from menu

URL design note: list is scoped by path (/by-event/{event_id}) rather than
query string because menus always exist WITHIN an event — this matches the
mental model and simplifies Dashboard fetching ('give me this event's menu').
Cross-event menu queries would be odd and aren't supported.

All errors follow backend contract §7.3 typed envelope.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.event_products.schemas import (
    EventProductCreate,
    EventProductResponse,
    EventProductUpdate,
)
from app.modules.event_products.service import (
    BarNotFoundError,
    BarNotInEventError,
    DuplicateMenuItemError,
    EventNotFoundError,
    EventProductNotFoundError,
    EventProductService,
    EventProductWithEffective,
    ProductArchivedError,
    ProductNotFoundError,
)


async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return current_user.tenant_id


router = APIRouter()


# ─── Response adapter ────────────────────────────────────────────────────────

def _to_response(item: EventProductWithEffective) -> EventProductResponse:
    """Flatten EventProductWithEffective into the wire response."""
    ep = item.event_product
    return EventProductResponse(
        id=ep.id,
        event_id=ep.event_id,
        bar_id=ep.bar_id,
        product_id=ep.product_id,
        price_cents=ep.price_cents,
        tier_rank_override=ep.tier_rank_override,
        effective_tier_rank=item.effective_tier_rank,
        is_available=ep.is_available,
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get(
    "/by-event/{event_id}",
    response_model=list[EventProductResponse],
)
async def list_menu_for_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    bar_id: Annotated[UUID | None, Query(description="Filter by bar")] = None,
    only_available: Annotated[bool, Query(description="Only is_available=true")] = False,
) -> list[EventProductResponse]:
    """Return the menu for an event, optionally scoped to a specific bar.

    Use cases:
    - Dashboard per-bar card: by-event/{event_id}?bar_id=X&only_available=true
    - Menu editor: by-event/{event_id} (all items incl. unavailable)
    - 404 if event doesn't exist (vs. silent empty list)
    """
    service = EventProductService(db)
    try:
        items = await service.list_for_event(
            tenant_id, event_id,
            bar_id=bar_id, only_available=only_available,
        )
    except EventNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    return [_to_response(i) for i in items]


@router.get("/{event_product_id}", response_model=EventProductResponse)
async def get_menu_item(
    event_product_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventProductResponse:
    """Fetch a single menu line."""
    service = EventProductService(db)
    try:
        item = await service.get_menu_item(tenant_id, event_product_id)
    except EventProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "menu_item_not_found", "message": str(e)},
        )
    return _to_response(item)


@router.post(
    "",
    response_model=EventProductResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_menu_item(
    payload: EventProductCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventProductResponse:
    """Add a product to an event's menu at a specific bar.

    Error responses:
    - 404 event_not_found / bar_not_found / product_not_found
    - 422 bar_not_in_event (bar exists but belongs to different event)
    - 422 product_archived (product soft-deleted)
    - 409 duplicate_menu_item (triple already exists; payload has existing_id)
    """
    service = EventProductService(db)
    try:
        item = await service.create_menu_item(tenant_id, payload)
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
    except DuplicateMenuItemError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_menu_item",
                "message": str(e),
                "existing_id": str(e.existing.id),
            },
        )
    return _to_response(item)


@router.patch("/{event_product_id}", response_model=EventProductResponse)
async def update_menu_item(
    event_product_id: UUID,
    payload: EventProductUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventProductResponse:
    """Update price, tier_rank_override, or is_available. FKs not patchable."""
    service = EventProductService(db)
    try:
        item = await service.update_menu_item(tenant_id, event_product_id, payload)
    except EventProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "menu_item_not_found", "message": str(e)},
        )
    return _to_response(item)


@router.delete(
    "/{event_product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_menu_item(
    event_product_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> None:
    """Remove a menu item. Use PATCH is_available=false for temporary disable."""
    service = EventProductService(db)
    try:
        await service.delete_menu_item(tenant_id, event_product_id)
    except EventProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "menu_item_not_found", "message": str(e)},
        )
