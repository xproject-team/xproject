"""HTTP router for the event_recipes module — input validation + response
formatting.

Endpoints under /api/v1/event-recipes (Catalog page's per-event recipe
editor, Chunk 2):

    GET    /{event_id}   list depletion rules for an event (+ read_only flag)
    POST   ""            create one row
    PATCH  /{id}         update ml_per_sale / is_optional
    DELETE /{id}         remove a row
    POST   /bulk         atomic add-only multi-row insert

Auth: any authenticated tenant user (matches other event-scoped
endpoints — this is a planning surface, not a destructive one; DRAFT
gating is what actually protects data integrity).
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.events.service import EventNotDraftError, EventNotFoundError
from app.modules.event_recipes.schemas import (
    EventRecipeBulkCreate,
    EventRecipeCreate,
    EventRecipeListResponse,
    EventRecipePatch,
    EventRecipeRow,
)
from app.modules.event_recipes.service import (
    BarNotFoundError,
    EventRecipeBulkValidationError,
    EventRecipeDuplicateError,
    EventRecipeNotFoundError,
    EventRecipeService,
    ProductNotFoundError,
    SupplierProductNotFoundError,
)


async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return current_user.tenant_id


router = APIRouter()


def _not_draft(e: EventNotDraftError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"error": "event_not_draft", "message": str(e)},
    )


@router.get("/{event_id}", response_model=EventRecipeListResponse)
async def list_event_recipes(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventRecipeListResponse:
    """List every depletion rule for the event. Always readable, even
    once the event has left DRAFT — `read_only` tells the FE to lock
    the editor instead of hiding the data."""
    service = EventRecipeService(db)
    try:
        rows, read_only = await service.list_for_event(tenant_id, event_id)
    except EventNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    return EventRecipeListResponse(rows=rows, read_only=read_only)


@router.post("", response_model=EventRecipeRow, status_code=status.HTTP_201_CREATED)
async def create_event_recipe(
    payload: EventRecipeCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventRecipeRow:
    service = EventRecipeService(db)
    try:
        return await service.create(tenant_id, payload)
    except EventNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    except EventNotDraftError as e:
        raise _not_draft(e)
    except BarNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "bar_not_found", "message": str(e)},
        )
    except SupplierProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "supplier_product_not_found", "message": str(e)},
        )
    except ProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except EventRecipeDuplicateError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "row_exists", "message": str(e)},
        )


@router.patch("/{row_id}", response_model=EventRecipeRow)
async def update_event_recipe(
    row_id: UUID,
    payload: EventRecipePatch,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventRecipeRow:
    service = EventRecipeService(db)
    try:
        return await service.update(tenant_id, row_id, payload)
    except EventRecipeNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_recipe_not_found", "message": str(e)},
        )
    except EventNotDraftError as e:
        raise _not_draft(e)


@router.delete("/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event_recipe(
    row_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> None:
    service = EventRecipeService(db)
    try:
        await service.delete(tenant_id, row_id)
    except EventRecipeNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_recipe_not_found", "message": str(e)},
        )
    except EventNotDraftError as e:
        raise _not_draft(e)


@router.post(
    "/bulk", response_model=list[EventRecipeRow], status_code=status.HTTP_201_CREATED,
)
async def bulk_create_event_recipes(
    payload: EventRecipeBulkCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> list[EventRecipeRow]:
    """Atomic add-only insert — used by the Catalog page's "Save all
    changes" button. Every row is validated before any write; one bad
    row rejects the whole batch (nothing partially inserted)."""
    service = EventRecipeService(db)
    try:
        return await service.bulk_create(tenant_id, payload)
    except EventNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    except EventNotDraftError as e:
        raise _not_draft(e)
    except EventRecipeBulkValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "event_recipes_bulk_validation_failed",
                "message": str(e),
                "items": [it.model_dump() for it in e.items],
            },
        )
