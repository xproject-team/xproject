"""Database queries for the events module — pure data access, no business logic.

Contract reference: §1.1 (4-layer architecture).
This file owns ALL SQL for the events domain. Services never write SQL.
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.events.models import Event, EventStatus
from app.modules.venues.models import Venue
from app.modules.events.schemas import EventCreate


class EventRepository:
    """Handles all SQL operations for Event records."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Reads ────────────────────────────────────────────────────────────────

    async def list_for_tenant(self, tenant_id: UUID) -> Sequence[Event]:
        """Return all events belonging to a given tenant, newest first.

        Eager-loads the venue relationship so EventResponse can render
        nested venue.name without an N+1 query.
        """
        stmt = (
            select(Event)
            .where(Event.tenant_id == tenant_id)
            .order_by(Event.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_id(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> Event | None:
        """Fetch a single event by ID, scoped to tenant.

        Returns None if not found OR if the event belongs to a different tenant.
        Tenant isolation is NON-NEGOTIABLE — always filter by tenant_id.
        """
        stmt = (
            select(Event)
            .where(Event.id == event_id)
            .where(Event.tenant_id == tenant_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def find_live_for_tenant(self, tenant_id: UUID) -> Event | None:
        """Return the tenant\'s currently LIVE event, or None.

        Invariant (contract §2.3): at most ONE live event per tenant,
        enforced at DB level by the one_live_event_per_tenant partial unique
        index. This query returns the single row or None.
        """
        stmt = (
            select(Event)
            .where(Event.tenant_id == tenant_id)
            .where(Event.status == EventStatus.LIVE)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def count_bars(self, event_id: UUID) -> int:
        """Return number of bars configured for this event.

        Used to populate EventResponse.bars_count. Imports the bars model
        locally to avoid a circular import with the bars module (which
        imports Event).
        """
        from app.modules.bars.models import Bar  # local import — see docstring
        stmt = (
            select(func.count())
            .select_from(Bar)
            .where(Bar.event_id == event_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def get_venue(self, tenant_id: UUID, venue_id: UUID) -> Venue | None:
        """Fetch a venue by ID, scoped to tenant.

        Used by service layer during POST/PATCH to validate the client\'s
        venue_id belongs to the same tenant.
        """
        stmt = (
            select(Venue)
            .where(Venue.id == venue_id)
            .where(Venue.tenant_id == tenant_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ─── Writes ───────────────────────────────────────────────────────────────

    async def create(self, tenant_id: UUID, data: EventCreate) -> Event:
        """Insert a new event for the given tenant.

        Flushes to assign id + populate server-side defaults (created_at,
        updated_at, version=1). Does NOT commit — service layer owns the
        transaction boundary (contract §1.5).
        """
        event = Event(
            tenant_id=tenant_id,
            name=data.name,
            venue_id=data.venue_id,
            scheduled_at=data.scheduled_at,
            scheduled_end_at=data.scheduled_end_at,
            expected_guest_count=data.expected_guest_count,
            stripe_ragione_sociale=data.stripe_ragione_sociale,
            staff_arrival_time=data.staff_arrival_time,
            wristband_qty_per_type=data.wristband_qty_per_type,
            topup_denominations_user=data.topup_denominations_user,
            topup_denominations_staff=data.topup_denominations_staff,
            refund_min_credit_cents=data.refund_min_credit_cents,
            refund_fee_cents=data.refund_fee_cents,
            refund_window_open_at=data.refund_window_open_at,
            refund_window_close_at=data.refund_window_close_at,
            status=EventStatus.DRAFT,
        )
        self.db.add(event)
        await self.db.flush()
        await self.db.refresh(event)
        return event

    async def update(
        self,
        event: Event,
        updates: dict,
    ) -> Event:
        """Apply `updates` dict to the event and bump version atomically.

        `updates` is a plain dict of {column_name: new_value} — the service
        layer has already validated that these fields are editable in the
        event\'s current status (via state_machine.assert_fields_editable).

        Version bump is automatic; callers should NOT include \'version\' in
        the updates dict. Flushes but does not commit.
        """
        for field, value in updates.items():
            setattr(event, field, value)
        event.version = event.version + 1
        await self.db.flush()
        await self.db.refresh(event)
        return event

    async def delete(self, event: Event) -> None:
        """Delete an event. Children (bars, products, etc.) CASCADE at DB level.

        Caller (service layer) must have verified the event is in DRAFT status
        per contract §3.3 before calling this. Flushes but does not commit.
        """
        await self.db.delete(event)
        await self.db.flush()
