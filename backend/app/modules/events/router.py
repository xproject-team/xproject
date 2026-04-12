"""HTTP router for the events module — input validation and response formatting only."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import Tenant
from app.modules.events.schemas import EventCreate, EventResponse
from app.modules.events.service import EventService


# ─── Temporary tenant resolver ────────────────────────────────────────────
# TODO(auth): replace with Clerk-authenticated user → tenant_id lookup.
# For Phase 5, every request is resolved as Noma Group by slug.
async def get_current_tenant_id(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UUID:
    """Resolve the current tenant. Hardcoded to 'noma-group' until auth ships."""
    result = await db.execute(select(Tenant).where(Tenant.slug == "noma-group"))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Seed tenant 'noma-group' not found. Run: python -m app.scripts.seed",
        )
    return tenant.id


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
