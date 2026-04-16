"""HTTP router for the venues module — input validation + response formatting.

Contract reference: §1.1 (thin router), §6 (endpoint inventory).
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.venues.schemas import VenueCreate, VenueResponse
from app.modules.venues.service import VenueNotFoundError, VenueService


async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return current_user.tenant_id


router = APIRouter()


@router.get("", response_model=list[VenueResponse])
async def list_venues(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> list[VenueResponse]:
    """List all venues for the current tenant, alphabetical."""
    service = VenueService(db)
    venues = await service.list_venues(tenant_id)
    return [VenueResponse.model_validate(v) for v in venues]


@router.get("/{venue_id}", response_model=VenueResponse)
async def get_venue(
    venue_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> VenueResponse:
    """Fetch a single venue by ID. 404 if not found / wrong tenant."""
    service = VenueService(db)
    try:
        venue = await service.get_venue(tenant_id, venue_id)
    except VenueNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "venue_not_found", "message": str(e)},
        )
    return VenueResponse.model_validate(venue)


@router.post("", response_model=VenueResponse, status_code=status.HTTP_201_CREATED)
async def create_venue(
    payload: VenueCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> VenueResponse:
    """Create a new venue for the current tenant."""
    service = VenueService(db)
    venue = await service.create_venue(tenant_id, payload)
    return VenueResponse.model_validate(venue)
