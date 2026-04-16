"""Database queries for the venues module — pure data access, no business logic.

Contract reference: §1.1 (4-layer architecture).
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.venues.models import Venue
from app.modules.venues.schemas import VenueCreate


class VenueRepository:
    """Handles all SQL operations for Venue records."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_tenant(self, tenant_id: UUID) -> Sequence[Venue]:
        """Return all venues for a tenant, alphabetical by name."""
        stmt = (
            select(Venue)
            .where(Venue.tenant_id == tenant_id)
            .order_by(Venue.name.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_id(
        self,
        tenant_id: UUID,
        venue_id: UUID,
    ) -> Venue | None:
        """Fetch a single venue by ID, scoped to tenant (tenant isolation)."""
        stmt = (
            select(Venue)
            .where(Venue.id == venue_id)
            .where(Venue.tenant_id == tenant_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, tenant_id: UUID, data: VenueCreate) -> Venue:
        """Insert a new venue. Flushes to assign id; services own commit."""
        venue = Venue(
            tenant_id=tenant_id,
            name=data.name,
            address=data.address,
            capacity=data.capacity,
        )
        self.db.add(venue)
        await self.db.flush()
        await self.db.refresh(venue)
        return venue
