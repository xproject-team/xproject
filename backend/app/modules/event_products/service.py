"""Business logic for the event_products module.

Beyond CRUD, this layer owns:

1. Cross-module validation on create:
   - event exists in tenant
   - bar exists in tenant AND belongs to that event (not cross-wired)
   - product exists in tenant AND is active (not archived)

2. Duplicate detection:
   - (event_id, bar_id, product_id) triple uniqueness via repo lookup,
     surfaced as a friendly 409 duplicate_menu_item

3. effective_tier_rank computation:
   - tier_rank_override if set, else Product.tier_rank (fetched via join
     in the repo)

Contract reference: §1.5 (service commits, repo flushes), §7.3 (typed errors).
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.repository import BarRepository
from app.modules.event_products.models import EventProduct
from app.modules.event_products.repository import EventProductRepository
from app.modules.event_products.schemas import (
    EventProductCreate,
    EventProductUpdate,
)
from app.modules.events.repository import EventRepository
from app.modules.products.repository import ProductRepository


# ─── Domain exceptions ────────────────────────────────────────────────────────

class EventProductNotFoundError(Exception):
    """Menu item does not exist or tenant mismatch. → 404."""


class EventNotFoundError(Exception):
    """Event referenced in create doesn't exist in tenant. → 404."""


class BarNotFoundError(Exception):
    """Bar referenced in create doesn't exist in tenant. → 404."""


class BarNotInEventError(Exception):
    """Bar exists but belongs to a different event. → 422."""


class ProductNotFoundError(Exception):
    """Product referenced in create doesn't exist in tenant. → 404."""


class ProductArchivedError(Exception):
    """Attempted to add an archived product to a menu. → 422."""


class DuplicateMenuItemError(Exception):
    """Same (event, bar, product) triple already exists. → 409.

    Payload includes the existing id so frontend can offer 'view existing'
    instead of silent failure.
    """
    def __init__(self, message: str, existing: EventProduct) -> None:
        super().__init__(message)
        self.existing = existing


# ─── Result DTO ───────────────────────────────────────────────────────────────

class EventProductWithEffective:
    """Bundle of (EventProduct, effective_tier_rank). Service returns these
    to the router so the response schema can populate effective_tier_rank
    without a second DB roundtrip.
    """
    __slots__ = ("event_product", "effective_tier_rank")

    def __init__(
        self,
        event_product: EventProduct,
        effective_tier_rank: int | None,
    ) -> None:
        self.event_product = event_product
        self.effective_tier_rank = effective_tier_rank


def _compute_effective(
    override: int | None,
    product_tier_rank: int | None,
) -> int | None:
    """override wins if set; otherwise fall back to catalog's tier_rank."""
    return override if override is not None else product_tier_rank


# ─── Service ──────────────────────────────────────────────────────────────────

class EventProductService:
    """All business logic for event_products."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = EventProductRepository(db)
        self.events = EventRepository(db)
        self.bars = BarRepository(db)
        self.products = ProductRepository(db)

    # ─── Read ─────────────────────────────────────────────────────────────────

    async def list_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        bar_id: UUID | None = None,
        only_available: bool = False,
    ) -> Sequence[EventProductWithEffective]:
        """List menu items for an event, optionally filtered by bar.

        Validates event exists in tenant first, so a 404 is returned for
        unknown events instead of an empty list (makes misuse obvious).
        """
        event = await self.events.get_by_id(tenant_id, event_id)
        if event is None:
            raise EventNotFoundError(f"Event {event_id} not found")

        rows = await self.repo.list_for_event(
            tenant_id, event_id,
            bar_id=bar_id, only_available=only_available,
        )
        return [
            EventProductWithEffective(
                ep, _compute_effective(ep.tier_rank_override, product_tier_rank),
            )
            for ep, product_tier_rank in rows
        ]

    async def get_menu_item(
        self,
        tenant_id: UUID,
        event_product_id: UUID,
    ) -> EventProductWithEffective:
        row = await self.repo.get_by_id(tenant_id, event_product_id)
        if row is None:
            raise EventProductNotFoundError(
                f"Menu item {event_product_id} not found"
            )
        ep, product_tier_rank = row
        return EventProductWithEffective(
            ep, _compute_effective(ep.tier_rank_override, product_tier_rank),
        )

    # ─── Create (the validation-heavy path) ──────────────────────────────────

    async def create_menu_item(
        self,
        tenant_id: UUID,
        data: EventProductCreate,
    ) -> EventProductWithEffective:
        """Create a new menu row after validating all cross-module constraints."""

        # 1. Event exists?
        event = await self.events.get_by_id(tenant_id, data.event_id)
        if event is None:
            raise EventNotFoundError(f"Event {data.event_id} not found")

        # 2. Bar exists AND belongs to this event?
        bar = await self.bars.get_by_id(tenant_id, data.bar_id)
        if bar is None:
            raise BarNotFoundError(f"Bar {data.bar_id} not found")
        if bar.event_id != data.event_id:
            raise BarNotInEventError(
                f"Bar {data.bar_id} belongs to a different event"
            )

        # 3. Product exists AND is active?
        product = await self.products.get_by_id(tenant_id, data.product_id)
        if product is None:
            raise ProductNotFoundError(f"Product {data.product_id} not found")
        if product.is_archived:
            raise ProductArchivedError(
                f"Product '{product.name}' is archived and cannot be added to a menu"
            )

        # 4. Dedup: same triple doesn't already exist
        existing = await self.repo.find_existing_triple(
            tenant_id, data.event_id, data.bar_id, data.product_id,
        )
        if existing is not None:
            raise DuplicateMenuItemError(
                f"'{product.name}' is already on the menu for this bar at this event.",
                existing=existing,
            )

        # 5. Persist
        ep = await self.repo.create(tenant_id, data)
        await self.db.commit()

        return EventProductWithEffective(
            ep,
            _compute_effective(ep.tier_rank_override, product.tier_rank),
        )

    # ─── Update ───────────────────────────────────────────────────────────────

    async def update_menu_item(
        self,
        tenant_id: UUID,
        event_product_id: UUID,
        data: EventProductUpdate,
    ) -> EventProductWithEffective:
        """Patch price / tier_rank_override / is_available. FKs not patchable."""
        row = await self.repo.get_by_id(tenant_id, event_product_id)
        if row is None:
            raise EventProductNotFoundError(
                f"Menu item {event_product_id} not found"
            )
        ep, product_tier_rank = row

        ep = await self.repo.update(ep, data)
        await self.db.commit()

        # Re-fetch product_tier_rank isn't needed — it doesn't change on update
        return EventProductWithEffective(
            ep,
            _compute_effective(ep.tier_rank_override, product_tier_rank),
        )

    # ─── Delete ───────────────────────────────────────────────────────────────

    async def delete_menu_item(
        self,
        tenant_id: UUID,
        event_product_id: UUID,
    ) -> None:
        row = await self.repo.get_by_id(tenant_id, event_product_id)
        if row is None:
            raise EventProductNotFoundError(
                f"Menu item {event_product_id} not found"
            )
        ep, _ = row
        await self.repo.delete(ep)
        await self.db.commit()
