"""Database queries for the events module — pure data access, no business logic."""
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event, EventStatus
from app.modules.events.schemas import EventCreate


class EventRepository:
    """Handles all SQL operations for Event records."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_tenant(self, tenant_id: UUID) -> Sequence[Event]:
        """Return all events belonging to a given tenant, newest first."""
        stmt = (
            select(Event)
            .where(Event.tenant_id == tenant_id)
            .order_by(Event.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def create(self, tenant_id: UUID, data: EventCreate) -> Event:
        """Insert a new event for the given tenant. Flushes to assign id."""
        event = Event(
            tenant_id=tenant_id,
            name=data.name,
            venue_id=data.venue_id,
            expected_guest_count=data.expected_guest_count,
            status=EventStatus.DRAFT,
        )
        self.db.add(event)
        await self.db.flush()
        await self.db.refresh(event)  # populate created_at / updated_at from DB
        return event
