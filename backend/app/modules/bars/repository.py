"""Database queries for the bars module — pure data access.

Contract reference: §1.1 (4-layer architecture).
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models import Bar
from app.modules.bars.schemas import BarCreate, BarUpdate


class BarRepository:
    """Handles all SQL operations for Bar records."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_tenant(self, tenant_id: UUID) -> Sequence[Bar]:
        """Return all bars for a tenant, ordered by name.

        Useful for admin/operations overview across all events.
        """
        stmt = (
            select(Bar)
            .where(Bar.tenant_id == tenant_id)
            .order_by(Bar.name.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
        only_active: bool = False,
    ) -> Sequence[Bar]:
        """Return all bars for a specific event, alphabetical.

        If only_active is True, filters out bars with is_active=False
        (soft-removed from event without deletion).
        """
        stmt = (
            select(Bar)
            .where(Bar.tenant_id == tenant_id)
            .where(Bar.event_id == event_id)
            .order_by(Bar.name.asc())
        )
        if only_active:
            stmt = stmt.where(Bar.is_active.is_(True))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_id(
        self,
        tenant_id: UUID,
        bar_id: UUID,
    ) -> Bar | None:
        """Fetch a single bar, scoped to tenant."""
        stmt = (
            select(Bar)
            .where(Bar.id == bar_id)
            .where(Bar.tenant_id == tenant_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, tenant_id: UUID, data: BarCreate) -> Bar:
        """Insert a new bar for an event. Service commits."""
        bar = Bar(
            tenant_id=tenant_id,
            event_id=data.event_id,
            name=data.name,
            slesh_negozio_id=data.slesh_negozio_id,
            bar_type=data.bar_type,
            device_count=data.device_count,
            slesh_category=data.slesh_category,
            is_active=data.is_active,
        )
        self.db.add(bar)
        await self.db.flush()
        await self.db.refresh(bar)
        return bar

    async def update(self, bar: Bar, data: BarUpdate) -> Bar:
        """Apply a partial update to a bar.

        Only fields set in the payload are mutated. event_id is not patchable
        at this layer (enforced by schema not including it in BarUpdate).
        """
        payload = data.model_dump(exclude_unset=True)
        for field, value in payload.items():
            setattr(bar, field, value)
        self.db.add(bar)
        await self.db.flush()
        await self.db.refresh(bar)
        return bar

    async def delete(self, bar: Bar) -> None:
        """Hard delete. For soft-remove, set is_active=False via update()."""
        await self.db.delete(bar)
        await self.db.flush()
