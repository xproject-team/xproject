"""Business logic for the bars module.

Currently thin — bars don't have a state machine of their own.
Add invariants here if/when they appear (e.g., max bars per event,
slesh_negozio_id uniqueness per tenant, validation against event status).

Contract reference: §1.5 (service commits, repo flushes).
"""
import logging
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models import Bar
from app.modules.bars.repository import BarRepository
from app.modules.bars.schemas import BarCreate, BarUpdate
from app.modules.events.repository import EventRepository
from app.modules.chat.service import ChatService

logger = logging.getLogger(__name__)
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
        """Create a new bar for an event. Validates event exists + in tenant.

        Also auto-creates the bar's chat channel. Chat creation is a soft
        dependency: if it fails, we log and continue — the bar is still
        created successfully, and a backfill script can fix missing channels
        later. This keeps bar creation independent of chat module health.
        """
        event = await self.events.get_by_id(tenant_id, data.event_id)
        if event is None:
            raise EventNotFoundForBarError(f"Event {data.event_id} not found")
        bar = await self.repo.create(tenant_id, data)

        # Auto-create the bar-team chat channel in the same transaction.
        # Wrapped in try/except so any chat-module issue never 500s bar
        # creation. The channel becomes an orphan only if the WHOLE tenant
        # owner row is missing — which is a separate data-integrity problem.
        try:
            chat = ChatService(self.db)
            await chat.create_bar_channel(
                bar_id=bar.id,
                bar_name=bar.name,
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to auto-create chat channel for bar %s (%s): %s",
                bar.id, bar.name, exc,
            )
            # Intentionally swallow: bar creation must succeed even if
            # chat provisioning has a transient hiccup.

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
    
    async def backfill_bar_channels(self, tenant_id: UUID) -> dict:
        """Idempotently create chat channels for any bars missing one.

        Intended for admin use after bulk data imports, seed runs, or
        backup restores that bypass BarService.create_bar (and therefore
        skip the auto-create-channel hook). Safe to call repeatedly:
        bars that already have a channel are left untouched.

        Returns a summary dict:
          { bars_scanned, channels_created, channels_already_present }
        """
        from sqlalchemy import select
        from app.modules.chat.models import Channel

        bars = await self.repo.list_for_tenant(tenant_id)
        chat = ChatService(self.db)

        bars_scanned = 0
        created = 0
        already_present = 0

        for bar in bars:
            bars_scanned += 1

            existing_stmt = select(Channel).where(
                Channel.bar_id == bar.id,
                Channel.channel_type == "bar",
                Channel.tenant_id == tenant_id,
            )
            existing = (await self.db.execute(existing_stmt)).scalar_one_or_none()
            if existing is not None:
                already_present += 1
                continue

            try:
                await chat.create_bar_channel(
                    bar_id=bar.id,
                    bar_name=bar.name,
                    tenant_id=tenant_id,
                )
                created += 1
            except Exception as exc:
                logger.warning(
                    "Backfill failed for bar %s (%s): %s",
                    bar.id, bar.name, exc,
                )

        await self.db.commit()

        return {
            "bars_scanned":            bars_scanned,
            "channels_created":        created,
            "channels_already_present": already_present,
        }