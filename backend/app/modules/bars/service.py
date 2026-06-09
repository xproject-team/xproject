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


class BarMergeInvalidError(Exception):
    """Merge request is structurally invalid (same src/dst, cross-event).
    Maps to 400."""


class BarMergeConflictError(Exception):
    """Merge cannot proceed due to data preconditions or routing conflicts
    (slesh_negozio_id mismatch, non-empty src, dst is itself a stub).
    Maps to 409."""


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

    async def merge_bars(
        self,
        tenant_id: UUID,
        src_id: UUID,
        dst_id: UUID,
    ) -> Bar:
        """Fold src bar into dst — the no-data-loss merge.

        Used by the Map Bars UI to reconcile auto-created stub bars
        (which the ingester creates for unmapped Slesh shop_ids) into
        properly-named bars. Reassigns src's stock_transactions, alerts,
        and user assignments to dst; moves src's slesh_negozio_id onto
        dst if dst lacks one; deletes src.

        Crash-safety: opens with SELECT ... FOR UPDATE on src so any
        concurrent Slesh ingest can't insert new stock_transactions on
        src while merge is in flight. Concurrent ingest either waits
        and rolls back with FK failure once src is deleted (the Slesh
        poller idempotently retries on the next cycle and finds dst),
        or commits before merge began, in which case its rows are
        picked up by the UPDATE reassignment.

        Refuses with BarMergeConflictError (409) if:
          - dst is itself an auto-created stub (wrong direction)
          - slesh_negozio_id values conflict (both bars mapped to
            different Slesh shops)
          - src has BarStock allocations, EventProduct menu rows, or
            chat Channels (these don't auto-merge cleanly)
        Refuses with BarMergeInvalidError (400) if:
          - src == dst
          - src and dst belong to different events
        Refuses with BarNotFoundError (404) if either bar is missing.

        Returns the surviving dst bar.
        """
        from sqlalchemy import func, select, update
        from app.modules.alerts.models import Alert
        from app.modules.auth.models import User as AuthUser
        from app.modules.bar_stock.models import BarStock
        from app.modules.chat.models import Channel
        from app.modules.event_products.models import EventProduct
        from app.modules.stock_transactions.models import StockTransaction

        if src_id == dst_id:
            raise BarMergeInvalidError(
                "source and destination bars must differ"
            )

        # SELECT FOR UPDATE locks src so any concurrent Slesh ingest
        # transaction blocks on the row lock rather than racing our
        # CASCADE delete to insert a new stock_transaction.
        src_stmt = (
            select(Bar)
            .where(Bar.tenant_id == tenant_id, Bar.id == src_id)
            .with_for_update()
        )
        src = (await self.db.execute(src_stmt)).scalar_one_or_none()
        if src is None:
            raise BarNotFoundError(f"Source bar {src_id} not found")

        dst_stmt = (
            select(Bar)
            .where(Bar.tenant_id == tenant_id, Bar.id == dst_id)
            .with_for_update()
        )
        dst = (await self.db.execute(dst_stmt)).scalar_one_or_none()
        if dst is None:
            raise BarNotFoundError(f"Destination bar {dst_id} not found")

        if src.event_id != dst.event_id:
            raise BarMergeInvalidError(
                "source and destination bars must belong to the same event"
            )

        if dst.auto_created:
            raise BarMergeConflictError(
                "destination is itself an auto-created stub; pick a "
                "properly named bar as the merge destination"
            )

        if (
            src.slesh_negozio_id is not None
            and dst.slesh_negozio_id is not None
            and src.slesh_negozio_id != dst.slesh_negozio_id
        ):
            raise BarMergeConflictError(
                f"destination is already mapped to Slesh shop "
                f"'{dst.slesh_negozio_id}'; cannot also accept "
                f"'{src.slesh_negozio_id}'"
            )

        # Preconditions on src — these tables don't auto-merge cleanly,
        # so the contract is that stubs are empty here (the ingester
        # never writes BarStock/EventProduct/Channel for an auto-created
        # bar). Refuse explicitly if the contract is violated.
        bs_count = await self.db.scalar(
            select(func.count()).select_from(BarStock).where(
                BarStock.bar_id == src.id
            )
        )
        if bs_count and bs_count > 0:
            raise BarMergeConflictError(
                f"source has {bs_count} stock allocation(s); clear them "
                f"first or choose a different destination"
            )

        ep_count = await self.db.scalar(
            select(func.count()).select_from(EventProduct).where(
                EventProduct.bar_id == src.id
            )
        )
        if ep_count and ep_count > 0:
            raise BarMergeConflictError(
                f"source has {ep_count} menu row(s); cannot merge"
            )

        ch_count = await self.db.scalar(
            select(func.count()).select_from(Channel).where(
                Channel.bar_id == src.id
            )
        )
        if ch_count and ch_count > 0:
            raise BarMergeConflictError(
                f"source has {ch_count} chat channel(s); cannot merge"
            )

        # Reassignments — all UPDATE-based so nothing cascade-deletes
        # when we drop src.
        await self.db.execute(
            update(StockTransaction)
            .where(StockTransaction.bar_id == src.id)
            .values(bar_id=dst.id)
        )
        await self.db.execute(
            update(Alert)
            .where(Alert.bar_id == src.id)
            .values(bar_id=dst.id)
        )
        await self.db.execute(
            update(AuthUser)
            .where(AuthUser.bar_id == src.id)
            .values(bar_id=dst.id)
        )

        # Move slesh_negozio_id onto dst if dst lacks one. Clear src
        # first to dodge any future unique constraint on the column.
        if src.slesh_negozio_id is not None and dst.slesh_negozio_id is None:
            transferred = src.slesh_negozio_id
            src.slesh_negozio_id = None
            await self.db.flush()
            dst.slesh_negozio_id = transferred
            await self.db.flush()

        # Drop src. Remaining FKs cascade (proposals/warehouse_scans
        # SET NULL; users already moved above so SET NULL is a no-op).
        await self.db.delete(src)
        await self.db.commit()

        return dst