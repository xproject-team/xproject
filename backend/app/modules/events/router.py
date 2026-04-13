"""HTTP router for the events module — input validation and response formatting only."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.events.schemas import EventCreate, EventResponse
from app.modules.events.service import EventService


# ─── Temporary tenant resolver ────────────────────────────────────────────
# TODO(auth): replace with Clerk-authenticated user → tenant_id lookup.
# For Phase 5, every request is resolved as Noma Group by slug.
async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    """Return the authenticated user's tenant_id (from JWT claims)."""
    return current_user.tenant_id


# ─── Router ──────────────────────────────────────────────────────────────
router = APIRouter()


@router.get("", response_model=list[EventResponse])
async def list_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> list[EventResponse]:
    """List all events for the current tenant, newest first."""
    service = EventService(db)
    events = await service.list_events(tenant_id)
    return [EventResponse.model_validate(e) for e in events]


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventResponse:
    """Create a new event for the current tenant."""
    service = EventService(db)
    event = await service.create_event(tenant_id, payload)
    return EventResponse.model_validate(event)
