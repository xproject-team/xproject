"""Business logic for the bars module.

Currently thin — bars don't have a state machine of their own.
Add invariants here if/when they appear (e.g., max bars per event,
slesh_negozio_id uniqueness per tenant, validation against event status).

Contract reference: §1.5 (service commits, repo flushes).
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models import Bar
from app.modules.bars.repository import BarRepository
from app.modules.bars.schemas import BarCreate, BarUpdate
from app.modules.events.repository import EventRepository


class BarNotFoundError(Exception):
    """Bar does not exist OR belongs to another tenant. Maps to 404."""


class EventNotFoundForBarError(Exception):
    """Bar references an event that doesn't exist/belong. Maps to 404."""


class BarService:
    """All business logic for bar operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = BarRepository(db)
        self.events = EventRepository(db)

    async def list_bars_for_tenant(self, tenant_id: UUID) -> Sequence[Bar]:
        """All bars for a tenant (operations/admin overview)."""
        return await self.repo.list_for_tenant(tenant_id)

    async def list_bars_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
        only_active: bool = False,
    ) -> Sequence[Bar]:
        """All bars for one event. Validates event exists in tenant first."""
        event = await self.events.get_by_id(tenant_id, event_id)
        if event is None:
            raise EventNotFoundForBarError(f"Event {event_id} not found")
        return await self.repo.list_for_event(tenant_id, event_id, only_active)

    async def get_bar(self, tenant_id: UUID, bar_id: UUID) -> Bar:
        """Fetch a single bar. Raises BarNotFoundError if missing."""
        bar = await self.repo.get_by_id(tenant_id, bar_id)
        if bar is None:
            raise BarNotFoundError(f"Bar {bar_id} not found")
        return bar

    async def create_bar(self, tenant_id: UUID, data: BarCreate) -> Bar:
        """Create a new bar for an event. Validates event exists + in tenant."""
        event = await self.events.get_by_id(tenant_id, data.event_id)
        if event is None:
            raise EventNotFoundForBarError(f"Event {data.event_id} not found")
        bar = await self.repo.create(tenant_id, data)
        await self.db.commit()
        return bar

    async def update_bar(
        self,
        tenant_id: UUID,
        bar_id: UUID,
        data: BarUpdate,
    ) -> Bar:
        """Patch a bar (partial update). 404 if not found in tenant."""
        bar = await self.get_bar(tenant_id, bar_id)
        bar = await self.repo.update(bar, data)
        await self.db.commit()
        return bar

    async def delete_bar(self, tenant_id: UUID, bar_id: UUID) -> None:
        """Hard delete a bar. 404 if not found. Consider is_active=False first."""
        bar = await self.get_bar(tenant_id, bar_id)
        await self.repo.delete(bar)
        await self.db.commit()
