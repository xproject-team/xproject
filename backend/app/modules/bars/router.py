"""HTTP router for the bars module — input validation + response formatting.

Contract reference: §1.1 (thin router), §6 (endpoint inventory).
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.bars.schemas import BarCreate, BarResponse, BarUpdate
from app.modules.bars.service import (
    BarNotFoundError,
    BarService,
    EventNotFoundForBarError,
)


async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return current_user.tenant_id


router = APIRouter()


@router.get("", response_model=list[BarResponse])
async def list_bars(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    event_id: Annotated[UUID | None, Query(description="Filter by event")] = None,
    only_active: Annotated[bool, Query(description="Only is_active=true bars")] = False,
) -> list[BarResponse]:
    """List bars. If event_id is given, scopes to that event; otherwise
    returns all bars in the tenant.

    Useful for:
    - Dashboard: list_bars(event_id=<live_event_id>, only_active=True)
    - Operations overview: list_bars() with no filter
    """
    service = BarService(db)
    if event_id is not None:
        try:
            bars = await service.list_bars_for_event(tenant_id, event_id, only_active)
        except EventNotFoundForBarError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "event_not_found", "message": str(e)},
            )
    else:
        bars = await service.list_bars_for_tenant(tenant_id)
    return [BarResponse.model_validate(b) for b in bars]


@router.get("/{bar_id}", response_model=BarResponse)
async def get_bar(
    bar_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> BarResponse:
    """Fetch a single bar by ID. 404 if not found in tenant."""
    service = BarService(db)
    try:
        bar = await service.get_bar(tenant_id, bar_id)
    except BarNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "bar_not_found", "message": str(e)},
        )
    return BarResponse.model_validate(bar)


@router.post("", response_model=BarResponse, status_code=status.HTTP_201_CREATED)
async def create_bar(
    payload: BarCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> BarResponse:
    """Create a new bar for an event. 404 if event doesn't exist in tenant."""
    service = BarService(db)
    try:
        bar = await service.create_bar(tenant_id, payload)
    except EventNotFoundForBarError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    return BarResponse.model_validate(bar)


@router.patch("/{bar_id}", response_model=BarResponse)
async def update_bar(
    bar_id: UUID,
    payload: BarUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> BarResponse:
    """Partial update. 404 if not found in tenant."""
    service = BarService(db)
    try:
        bar = await service.update_bar(tenant_id, bar_id, payload)
    except BarNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "bar_not_found", "message": str(e)},
        )
    return BarResponse.model_validate(bar)


@router.delete("/{bar_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bar(
    bar_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> None:
    """Hard delete. 404 if not found in tenant.

    Note: for preserving transaction history, consider PATCH with
    is_active=False instead of deleting.
    """
    service = BarService(db)
    try:
        await service.delete_bar(tenant_id, bar_id)
    except BarNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "bar_not_found", "message": str(e)},
        )
