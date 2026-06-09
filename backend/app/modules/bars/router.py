"""HTTP router for the bars module — input validation + response formatting.

Contract reference: §1.1 (thin router), §6 (endpoint inventory).
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User, UserRole
from app.modules.auth.router import get_current_user
from app.modules.auth.permissions import get_active_role
from app.modules.bars.schemas import BarCreate, BarResponse, BarUpdate
from app.modules.bars.service import (
    BarMergeConflictError,
    BarMergeInvalidError,
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
@router.post(
    "/backfill-channels",
    status_code=status.HTTP_200_OK,
)
async def backfill_channels(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Owner-only: idempotently create chat channels for bars missing one.

    Intended for fixing data inconsistencies after bulk imports, seed runs,
    or backup restores. Safe to call repeatedly — bars that already have
    a channel are left untouched.

    Returns a summary:
      { bars_scanned, channels_created, channels_already_present }

    403 if caller is not the tenant Owner.
    """
    if get_active_role(current_user) != UserRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "owner_only",
                "message": "Only the tenant Owner can trigger channel backfill.",
            },
        )

    service = BarService(db)
    summary = await service.backfill_bar_channels(current_user.tenant_id)
    return summary


@router.post(
    "/{src_id}/merge-into/{dst_id}",
    response_model=BarResponse,
    status_code=status.HTTP_200_OK,
)
async def merge_bars_endpoint(
    src_id: UUID,
    dst_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> BarResponse:
    """Owner-only: fold src bar into dst.

    Reconciles an auto-created stub bar (which the ingester mints for
    unmapped Slesh shop_ids) into a properly-named bar that already
    exists. Transfers all stock_transactions, alerts, and user
    assignments, and routes future Slesh orders for the same shop_id
    to dst. The src bar is deleted.

    Errors:
      400 if src == dst, or bars belong to different events.
      404 if either bar doesn't exist in tenant.
      409 if dst is itself an auto-created stub, slesh_negozio_id
          values conflict, or src has stock allocations / menu rows /
          chat channels (none of these auto-merge cleanly).
      403 if caller is not the Owner.
    """
    if get_active_role(current_user) != UserRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error":   "owner_only",
                "message": "Only the tenant Owner can merge bars.",
            },
        )

    service = BarService(db)
    try:
        dst = await service.merge_bars(current_user.tenant_id, src_id, dst_id)
    except BarNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "bar_not_found", "message": str(e)},
        )
    except BarMergeInvalidError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "bar_merge_invalid", "message": str(e)},
        )
    except BarMergeConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "bar_merge_conflict", "message": str(e)},
        )

    return dst