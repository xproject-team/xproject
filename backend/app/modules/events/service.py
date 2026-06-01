"""Business logic for the events module — orchestrates repository calls.

Contract reference: §1.1 (layered architecture), §1.5 (service owns transactions).

The service layer:
  1. Validates tenant scoping (never trusts router to filter by tenant).
  2. Enforces state machine + field lock rules via state_machine module.
  3. Enforces optimistic locking (version check) on PATCH.
  4. Enforces one-live-per-tenant invariant on /start.
  5. Owns the transaction boundary: repositories flush, services commit.
  6. Translates domain concerns into typed exceptions; router translates
     those into HTTP status codes.
"""
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event, EventStatus
from app.modules.events.repository import EventRepository
from app.modules.events.schemas import EventCreate, EventUpdate
from app.modules.events.state_machine import (
    FieldLockedError,
    InvalidTransitionError,
    assert_fields_editable,
    assert_transition_allowed,
)


# ─── Domain exceptions ────────────────────────────────────────────────────────
# Router layer maps each to the appropriate HTTP status code.

class EventNotFoundError(Exception):
    """Event does not exist OR belongs to a different tenant. Maps to 404."""


class VenueNotFoundError(Exception):
    """Venue does not exist OR belongs to a different tenant. Maps to 404."""


class StaleVersionError(Exception):
    """Client submitted an outdated version number. Maps to 409.

    Contract §4 (optimistic locking): always include current_version so
    the frontend can re-fetch.
    """
    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(
            f"Event was modified by someone else (current version: {current_version})"
        )


class LiveEventConflictError(Exception):
    """Another event in the same tenant is currently Live. Maps to 409.

    Contract §2.3 + Q1: at most ONE live event per tenant. If the
    conflicting event\'s ended_at has passed, service auto-ends it in the
    same transaction. Otherwise raises this error with conflicting_event info.
    """
    def __init__(self, conflicting_event: Event) -> None:
        self.conflicting_event = conflicting_event
        super().__init__(
            f"Cannot go live: event {conflicting_event.name!r} is currently live. End it first."
        )


# ─── Service ──────────────────────────────────────────────────────────────────

class EventService:
    """All business logic for event operations.

    Services commit transactions. Repositories only flush. This lets a
    single service call orchestrate multiple repository operations atomically.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = EventRepository(db)

    # ─── Reads ────────────────────────────────────────────────────────────────

    async def list_events(self, tenant_id: UUID) -> Sequence[Event]:
        """List all events for a tenant."""
        return await self.repo.list_for_tenant(tenant_id)

    async def get_event(self, tenant_id: UUID, event_id: UUID) -> Event:
        """Fetch a single event. Raises EventNotFoundError if missing."""
        event = await self.repo.get_by_id(tenant_id, event_id)
        if event is None:
            raise EventNotFoundError(f"Event {event_id} not found")
        return event

    # ─── Create ───────────────────────────────────────────────────────────────

    async def create_event(self, tenant_id: UUID, data: EventCreate) -> Event:
        """Create a new event. Validates venue belongs to same tenant.

        New events always start at DRAFT (not client-controlled).
        """
        venue = await self.repo.get_venue(tenant_id, data.venue_id)
        if venue is None:
            raise VenueNotFoundError(f"Venue {data.venue_id} not found")
        event = await self.repo.create(tenant_id, data)
        await self.db.commit()
        return event

    # ─── Update ───────────────────────────────────────────────────────────────

    async def update_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
        data: EventUpdate,
    ) -> Event:
        """Update editable fields on an event.

        Enforces (in this order):
          1. Event exists + belongs to tenant (404 if not)
          2. Version match (409 StaleVersion if client\'s version is outdated)
          3. Field-lock rules per current status (409 FieldLocked on live/completed)
          4. Venue validity if venue_id is being changed (404 if venue missing)
        """
        event = await self.get_event(tenant_id, event_id)

        # 1. Optimistic locking
        if event.version != data.version:
            raise StaleVersionError(current_version=event.version)

        # 2. Compute the set of fields actually being changed (client sends
        #    only non-None values to indicate intent).
        updates = data.model_dump(exclude={"version"}, exclude_none=True)
        if not updates:
            return event  # no-op, still return current state

        # 3. Field-lock enforcement per status
        assert_fields_editable(event.status, set(updates.keys()))

        # 4. If venue_id is changing, validate the new venue exists + same tenant
        if "venue_id" in updates:
            new_venue = await self.repo.get_venue(tenant_id, updates["venue_id"])
            if new_venue is None:
                raise VenueNotFoundError(f"Venue {updates["venue_id"]} not found")

        # 5. Apply updates + bump version (repo handles the SET, we commit)
        await self.repo.update(event, updates)
        await self.db.commit()

        # 6. Fire-and-forget auto-regen of predictions when fields that affect
        #    forecasts changed. Per docs/predictions-module-spec.md §6.3, only
        #    expected_guest_count matters in this endpoint (bars + menu live
        #    in their own endpoints and trigger their own regens). The hook
        #    SWALLOWS failures internally — a prediction problem must never
        #    break the event update that triggered it.
        prediction_relevant = {"expected_guest_count"}
        if prediction_relevant.intersection(updates.keys()):
            from app.modules.predictions.service import PredictionService
            await PredictionService(self.db).trigger_auto_regen_for_event(
                tenant_id=tenant_id,
                event_id=event_id,
            )

        return event

    # ─── Delete ───────────────────────────────────────────────────────────────

    async def delete_event(self, tenant_id: UUID, event_id: UUID) -> None:
        """Delete a DRAFT event (children CASCADE). Other statuses return 409.

        Contract §3.3: only DRAFT events can be deleted. Active/Live/Completed
        use End Event instead.
        """
        event = await self.get_event(tenant_id, event_id)
        if event.status != EventStatus.DRAFT:
            raise InvalidTransitionError(event.status, EventStatus.CANCELLED)
        await self.repo.delete(event)
        await self.db.commit()

    # ─── Status transitions ───────────────────────────────────────────────────

    async def activate_event(self, tenant_id: UUID, event_id: UUID) -> Event:
        """Draft → Active. Idempotent: calling on Active event returns current."""
        event = await self.get_event(tenant_id, event_id)
        assert_transition_allowed(event.status, EventStatus.ACTIVE)
        if event.status == EventStatus.ACTIVE:
            return event  # idempotent no-op
        await self.repo.update(event, {"status": EventStatus.ACTIVE})
        await self.db.commit()
        return event

    async def start_event(self, tenant_id: UUID, event_id: UUID) -> Event:
        """Active → Live. Enforces one-live-per-tenant with auto-end-if-stale.

        Contract Q1 (hybrid): if another event is currently Live AND its
        ended_at has already passed, auto-end it in the same transaction,
        then start the requested one. If the conflicting event is still
        "genuinely" live (ended_at in future or NULL), raise LiveEventConflict.
        """
        event = await self.get_event(tenant_id, event_id)
        assert_transition_allowed(event.status, EventStatus.LIVE)
        if event.status == EventStatus.LIVE:
            return event  # idempotent

        # Check for another live event in this tenant
        existing_live = await self.repo.find_live_for_tenant(tenant_id)
        if existing_live is not None and existing_live.id != event.id:
            now = datetime.now(timezone.utc)
            if existing_live.ended_at is not None and existing_live.ended_at < now:
                # Stale live event — auto-end it (same transaction)
                await self.repo.update(
                    existing_live,
                    {"status": EventStatus.COMPLETED},
                )
            else:
                # Genuinely live — refuse
                raise LiveEventConflictError(conflicting_event=existing_live)

        # Transition the requested event to Live
        await self.repo.update(
            event,
            {
                "status": EventStatus.LIVE,
                "started_at": datetime.now(timezone.utc),
            },
        )
        await self.db.commit()
        return event

    async def end_event(self, tenant_id: UUID, event_id: UUID) -> Event:
        """Live → Completed. Idempotent."""
        event = await self.get_event(tenant_id, event_id)
        assert_transition_allowed(event.status, EventStatus.COMPLETED)
        if event.status == EventStatus.COMPLETED:
            return event  # idempotent
        await self.repo.update(
            event,
            {
                "status": EventStatus.COMPLETED,
                "ended_at": datetime.now(timezone.utc),
            },
        )
        await self.db.commit()
        return event

    # ─── Response building ────────────────────────────────────────────────────

    async def build_response_dict(self, event: Event) -> dict:
        """Build the EventResponse dict for an event, including computed fields.

        - bars_count: COUNT(bars) query
        - venue: loaded via explicit query (to avoid N+1 on list endpoint, we
          eager-load in the repository\'s list method)
        """
        from app.modules.events.schemas import VenueResponse
        bars_count = await self.repo.count_bars(event.id)
        venue = await self.repo.get_venue(event.tenant_id, event.venue_id)
        return {
            "id": event.id,
            "tenant_id": event.tenant_id,
            "name": event.name,
            "status": event.status,
            "scheduled_at": event.scheduled_at,
            "scheduled_end_at": event.scheduled_end_at,
            "venue": VenueResponse.model_validate(venue),
            "expected_guest_count": event.expected_guest_count,
            "bars_count": bars_count,
            "version": event.version,
            "started_at": event.started_at,
            "ended_at": event.ended_at,
            "created_at": event.created_at,
            "updated_at": event.updated_at,
        }
