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
import logging
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

logger = logging.getLogger(__name__)

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

from app.modules.events.schemas import (
    FullEventCreate,
    FullEventItemError,
)


class FullEventValidationError(Exception):
    """Composite event create rejected — one or more items invalid."""

    def __init__(self, errors: list[FullEventItemError]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} invalid item(s) in full event payload")


class EventNotDraftError(Exception):
    """Composite update attempted on a non-DRAFT event (restructure unsafe)."""


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


async def _enqueue_nowcast_retrain(tenant_id: UUID) -> None:
    """Best-effort: queue a Phase F nowcast retrain (see
    app/workers/tasks.py::retrain_predictor) after this tenant's event
    completes.

    Failure here (Redis down, transient network blip) must NEVER
    surface to end_event()'s caller — the event has already completed
    and that transaction has already committed by the time this runs.
    Retraining is a background improvement, not part of the event
    lifecycle's correctness; if this enqueue fails, the predictor just
    keeps serving its previous training set until the next completed
    event successfully triggers a retrain (or an operator re-runs it
    manually).

    No existing precedent in this codebase for enqueueing an arq job
    from request-time service code (the only prior examples enqueue
    from inside another already-running arq task, via ctx["redis"]) —
    so this opens its own short-lived connection pool per call. Event
    completion is a low-frequency admin action, not a hot path, so the
    extra connection-setup latency is an acceptable, isolated cost.
    """
    try:
        from arq.connections import RedisSettings, create_pool

        from app.core.config import settings

        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            await redis.enqueue_job(
                "retrain_predictor",
                str(tenant_id),
                _job_id=f"nowcast-retrain:{tenant_id}",
            )
        finally:
            await redis.close()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Failed to enqueue nowcast retrain for tenant=%s: %s", tenant_id, e,
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

    # ─── Full create / update (Phase D — Create Event wizard composite) ──────

    def _validate_full(self, data) -> list:
        """Validate a composite payload. Returns list[FullEventItemError]."""
        from app.modules.events.schemas import FullEventItemError
        from app.modules.products.service import _validate_shape

        errors = []
        n_bars, n_products = len(data.bars), len(data.products)

        seen_products = set()
        for i, prod in enumerate(data.products):
            key = (prod.name.strip().lower(), str(prod.product_type))
            if key in seen_products:
                errors.append(FullEventItemError(
                    section="products", index=i,
                    error=f"duplicate product '{prod.name}' in payload",
                ))
            seen_products.add(key)
            try:
                _validate_shape(prod.product_type, prod.category, prod.tier_rank)
            except Exception as exc:
                errors.append(FullEventItemError(
                    section="products", index=i, error=str(exc),
                ))

        def _check(section, rows):
            seen = set()
            for i, r in enumerate(rows):
                if r.bar_index >= n_bars:
                    errors.append(FullEventItemError(
                        section=section, index=i,
                        error=f"bar_index {r.bar_index} out of range (bars: {n_bars})",
                    ))
                if r.product_index >= n_products:
                    errors.append(FullEventItemError(
                        section=section, index=i,
                        error=(
                            f"product_index {r.product_index} out of range "
                            f"(products: {n_products})"
                        ),
                    ))
                key = (r.bar_index, r.product_index)
                if key in seen:
                    errors.append(FullEventItemError(
                        section=section, index=i,
                        error=f"duplicate (bar_index, product_index) pair {key}",
                    ))
                seen.add(key)

        _check("menu", data.menu)
        _check("allocations", data.allocations)
        return errors

    async def _create_children(self, tenant_id, event, data) -> dict:
        """Create bars + products + menu + allocations for an event. No commit."""
        from sqlalchemy import func, select

        from app.modules.bar_stock.models import BarStock
        from app.modules.bars.models import Bar
        from app.modules.chat.service import ChatService
        from app.modules.event_products.models import EventProduct
        from app.modules.products.models import Product
        from app.modules.products.service import derive_tier_rank

        bar_rows = []
        chat = ChatService(self.db)
        for b in data.bars:
            bar = Bar(
                tenant_id=tenant_id, event_id=event.id, name=b.name,
                slesh_negozio_id=b.slesh_negozio_id, bar_type=b.bar_type,
                device_count=b.device_count, slesh_category=b.slesh_category,
                is_active=b.is_active,
            )
            self.db.add(bar)
            await self.db.flush()
            bar_rows.append(bar)
            try:
                await chat.create_bar_channel(
                    bar_id=bar.id, bar_name=bar.name, tenant_id=tenant_id,
                )
            except Exception:
                pass  # soft dependency, same policy as BarService.create_bar

        product_rows = []
        products_created = products_reused = 0
        for prod in data.products:
            existing = (
                await self.db.execute(
                    select(Product).where(
                        Product.tenant_id == tenant_id,
                        func.lower(Product.name) == prod.name.strip().lower(),
                        Product.product_type == prod.product_type,
                        Product.is_archived == False,  # noqa: E712
                    )
                )
            ).scalars().first()
            if existing is not None:
                product_rows.append(existing)
                products_reused += 1
                continue
            row = Product(
                tenant_id=tenant_id, name=prod.name.strip(),
                product_type=prod.product_type, category=prod.category,
                tier_rank=derive_tier_rank(
                    prod.product_type, prod.category, prod.tier_rank,
                ),
                unit=prod.unit, default_price_cents=prod.default_price_cents,
                external_pos_id=None, barcode=None, iva_pct=prod.iva_pct,
                cauzione_cents=prod.cauzione_cents, food_type=prod.food_type,
                is_archived=False,
            )
            self.db.add(row)
            await self.db.flush()
            product_rows.append(row)
            products_created += 1

        for mrow in data.menu:
            self.db.add(EventProduct(
                tenant_id=tenant_id, event_id=event.id,
                bar_id=bar_rows[mrow.bar_index].id,
                product_id=product_rows[mrow.product_index].id,
                price_cents=mrow.price_cents,
                tier_rank_override=mrow.tier_rank_override,
                is_available=mrow.is_available,
            ))
        await self.db.flush()

        allocations_created = 0
        for arow in data.allocations:
            if arow.qty == 0:
                continue
            self.db.add(BarStock(
                tenant_id=tenant_id, event_id=event.id,
                bar_id=bar_rows[arow.bar_index].id,
                product_id=product_rows[arow.product_index].id,
                allocated_qty=arow.qty, current_qty=arow.qty, returned_qty=0,
            ))
            allocations_created += 1
        await self.db.flush()

        return {
            "bars_created": len(bar_rows),
            "products_created": products_created,
            "products_reused": products_reused,
            "menu_items_created": len(data.menu),
            "allocations_created": allocations_created,
        }

    async def create_full(self, tenant_id: UUID, data) -> dict:
        """Create a complete event in ONE transaction (Phase D wizard)."""
        venue = await self.repo.get_venue(tenant_id, data.event.venue_id)
        if venue is None:
            raise VenueNotFoundError(f"Venue {data.event.venue_id} not found")
        errors = self._validate_full(data)
        if errors:
            raise FullEventValidationError(errors)
        event = await self.repo.create(tenant_id, data.event)
        counts = await self._create_children(tenant_id, event, data)
        await self.db.commit()
        return {"event": event, **counts}

    async def update_full(self, tenant_id: UUID, event_id: UUID, data) -> dict:
        """Restructure a DRAFT event from the wizard. Replace semantics:
        update scalar fields, delete bars (cascades event_products +
        bar_stock), recreate from payload. DRAFT-only — restructuring a
        LIVE event would orphan transactions.
        """
        from sqlalchemy import delete as sa_delete

        from app.modules.bars.models import Bar
        from app.modules.events.models import EventStatus

        event = await self.get_event(tenant_id, event_id)
        if event is None:
            raise EventNotFoundError(f"Event {event_id} not found")
        if event.status != EventStatus.DRAFT:
            raise EventNotDraftError(
                f"Event {event_id} is {event.status}; only DRAFT events "
                f"can be restructured via the wizard"
            )
        venue = await self.repo.get_venue(tenant_id, data.event.venue_id)
        if venue is None:
            raise VenueNotFoundError(f"Venue {data.event.venue_id} not found")
        errors = self._validate_full(data)
        if errors:
            raise FullEventValidationError(errors)

        e = data.event
        event.name = e.name
        event.venue_id = e.venue_id
        event.scheduled_at = e.scheduled_at
        event.scheduled_end_at = e.scheduled_end_at
        event.expected_guest_count = e.expected_guest_count
        event.stripe_ragione_sociale = e.stripe_ragione_sociale
        event.staff_arrival_time = e.staff_arrival_time
        event.wristband_qty_per_type = e.wristband_qty_per_type
        event.topup_denominations_user = e.topup_denominations_user
        event.topup_denominations_staff = e.topup_denominations_staff
        event.refund_min_credit_cents = e.refund_min_credit_cents
        event.refund_fee_cents = e.refund_fee_cents
        event.refund_window_open_at = e.refund_window_open_at
        event.refund_window_close_at = e.refund_window_close_at
        event.food_revenue_share_pct = e.food_revenue_share_pct
        event.version = event.version + 1

        # Replace children: delete bars cascades event_products + bar_stock
        await self.db.execute(sa_delete(Bar).where(Bar.event_id == event.id))
        await self.db.flush()
        counts = await self._create_children(tenant_id, event, data)
        await self.db.commit()
        return {"event": event, **counts}

    async def get_full(self, tenant_id: UUID, event_id: UUID) -> dict:
        """Read event + bars + referenced products + menu + allocations.

        Returns a dict matching FullEventDetail (event is the ORM Event; the
        router calls build_response_dict to convert). Only products
        REFERENCED by this event's menu or allocations are included.

        Inverse of _create_children — SELECT only, no side effects. Ordering
        is deterministic (bars: created_at,id; products: name,id; menu +
        allocations: bar_index,product_index) so the wizard can round-trip
        against stable indices.

        Raises EventNotFoundError if not found or wrong tenant.
        """
        from sqlalchemy import select

        from app.modules.bar_stock.models import BarStock
        from app.modules.bars.models import Bar
        from app.modules.event_products.models import EventProduct
        from app.modules.products.models import Product
        from app.modules.events.schemas import (
            FullEventAllocation,
            FullEventBar,
            FullEventMenuItem,
            FullEventProductInput,
        )

        # 404 (also cross-tenant) — reuse the tenant-scoped fetch.
        event = await self.get_event(tenant_id, event_id)

        # ── Bars: created_at ASC, id ASC ───────────────────────────────────
        bar_orm = (
            (
                await self.db.execute(
                    select(Bar)
                    .where(Bar.tenant_id == tenant_id, Bar.event_id == event_id)
                    .order_by(Bar.created_at.asc(), Bar.id.asc())
                )
            )
            .scalars()
            .all()
        )
        bar_index = {b.id: i for i, b in enumerate(bar_orm)}

        # ── Menu + allocation rows for this event ──────────────────────────
        menu_orm = (
            (
                await self.db.execute(
                    select(EventProduct).where(
                        EventProduct.tenant_id == tenant_id,
                        EventProduct.event_id == event_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        alloc_orm = (
            (
                await self.db.execute(
                    select(BarStock).where(
                        BarStock.tenant_id == tenant_id,
                        BarStock.event_id == event_id,
                    )
                )
            )
            .scalars()
            .all()
        )

        # ── Products: union referenced by menu ∪ allocations, name/id ASC ──
        referenced_ids = {m.product_id for m in menu_orm} | {
            a.product_id for a in alloc_orm
        }
        product_orm = []
        if referenced_ids:
            product_orm = (
                (
                    await self.db.execute(
                        select(Product)
                        .where(
                            Product.tenant_id == tenant_id,
                            Product.id.in_(referenced_ids),
                        )
                        .order_by(Product.name.asc(), Product.id.asc())
                    )
                )
                .scalars()
                .all()
            )
        product_index = {p.id: i for i, p in enumerate(product_orm)}

        bars = [
            FullEventBar.model_validate(b, from_attributes=True) for b in bar_orm
        ]
        products = [
            FullEventProductInput.model_validate(p, from_attributes=True)
            for p in product_orm
        ]

        # ── Menu: emit sorted by (bar_index, product_index) ────────────────
        # Defensive: skip any row whose bar/product isn't in the ordered sets
        # (can't happen given FK + how referenced_ids is built, but never raise).
        menu_items = []
        for m in menu_orm:
            bi = bar_index.get(m.bar_id)
            pi = product_index.get(m.product_id)
            if bi is None or pi is None:
                continue
            menu_items.append(
                FullEventMenuItem(
                    bar_index=bi,
                    product_index=pi,
                    price_cents=m.price_cents,
                    tier_rank_override=m.tier_rank_override,
                    is_available=m.is_available,
                )
            )
        menu_items.sort(key=lambda x: (x.bar_index, x.product_index))

        # ── Allocations: qty ← bar_stock.allocated_qty, same ordering ──────
        allocations = []
        for a in alloc_orm:
            bi = bar_index.get(a.bar_id)
            pi = product_index.get(a.product_id)
            if bi is None or pi is None:
                continue
            allocations.append(
                FullEventAllocation(
                    bar_index=bi,
                    product_index=pi,
                    qty=int(a.allocated_qty),
                )
            )
        allocations.sort(key=lambda x: (x.bar_index, x.product_index))

        return {
            "event": event,
            "bars": bars,
            "products": products,
            "menu": menu_items,
            "allocations": allocations,
        }

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
        # Phase F: queue a nowcast retrain now that this event has real,
        # closed-book revenue data. Enqueued AFTER commit (not before) —
        # a job for a transaction that never actually landed would be
        # worse than no job at all. Best-effort: see
        # _enqueue_nowcast_retrain's docstring for why a Redis hiccup
        # here must never surface to this method's caller.
        await _enqueue_nowcast_retrain(tenant_id)
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
            "stripe_ragione_sociale": event.stripe_ragione_sociale,
            "staff_arrival_time": event.staff_arrival_time,
            "wristband_qty_per_type": event.wristband_qty_per_type,
            "topup_denominations_user": event.topup_denominations_user,
            "topup_denominations_staff": event.topup_denominations_staff,
            "refund_min_credit_cents": event.refund_min_credit_cents,
            "refund_fee_cents": event.refund_fee_cents,
            "refund_window_open_at": event.refund_window_open_at,
            "refund_window_close_at": event.refund_window_close_at,
            "bars_count": bars_count,
            "version": event.version,
            "started_at": event.started_at,
            "ended_at": event.ended_at,
            "created_at": event.created_at,
            "updated_at": event.updated_at,
        }
