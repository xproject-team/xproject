"""Business logic for the events module — orchestrates repository calls."""
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event
from app.modules.events.repository import EventRepository
from app.modules.events.schemas import EventCreate


class EventService:
    """Contains all business logic for event operations.

    The service is the only layer that commits transactions. Repositories
    flush; services commit. This lets a single service call orchestrate
    multiple repository operations atomically.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = EventRepository(db)

    async def list_events(self, tenant_id: UUID) -> Sequence[Event]:
        """List all events for a tenant."""
        return await self.repo.list_for_tenant(tenant_id)

    async def create_event(self, tenant_id: UUID, data: EventCreate) -> Event:
        """Create a new event for a tenant and commit the transaction."""
        event = await self.repo.create(tenant_id, data)
        await self.db.commit()
        return event
