"""Business logic for the venues module.

Currently thin — venues don't have a state machine or complex invariants.
Extract invariants here if/when they appear (capacity vs. expected_guests
validation on Event creation, floor plan sanity checks, etc.).

Contract reference: §1.5 (service commits, repo flushes).
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.venues.models import Venue
from app.modules.venues.repository import VenueRepository
from app.modules.venues.schemas import VenueCreate


class VenueNotFoundError(Exception):
    """Venue does not exist OR belongs to a different tenant. Maps to 404."""


class VenueService:
    """All business logic for venue operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = VenueRepository(db)

    async def list_venues(self, tenant_id: UUID) -> Sequence[Venue]:
        """List all venues for a tenant."""
        return await self.repo.list_for_tenant(tenant_id)

    async def get_venue(self, tenant_id: UUID, venue_id: UUID) -> Venue:
        """Fetch a single venue. Raises VenueNotFoundError if missing."""
        venue = await self.repo.get_by_id(tenant_id, venue_id)
        if venue is None:
            raise VenueNotFoundError(f"Venue {venue_id} not found")
        return venue

    async def create_venue(self, tenant_id: UUID, data: VenueCreate) -> Venue:
        """Create a new venue for the tenant."""
        venue = await self.repo.create(tenant_id, data)
        await self.db.commit()
        return venue
