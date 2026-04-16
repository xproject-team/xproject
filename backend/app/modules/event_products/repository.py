"""Database queries for the event_products module.

Design notes:
- list_for_event and get_by_id JOIN with products to fetch the catalog's
  tier_rank — the service then computes effective_tier_rank from
  (override OR catalog default).
- find_existing_triple is used by service before create, to return a
  friendly 409 duplicate_menu_item instead of a raw IntegrityError from
  the unique index on (event_id, bar_id, product_id).

Contract reference: §1.1 (4-layer architecture).
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.event_products.models import EventProduct
from app.modules.event_products.schemas import (
    EventProductCreate,
    EventProductUpdate,
)
from app.modules.products.models import Product


class EventProductRepository:
    """Handles all SQL operations for event_products."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Read ─────────────────────────────────────────────────────────────────

    async def list_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        bar_id: UUID | None = None,
        only_available: bool = False,
    ) -> Sequence[tuple[EventProduct, int | None]]:
        """Return (EventProduct, Product.tier_rank) tuples for an event.

        Service uses Product.tier_rank as the fallback when
        EventProduct.tier_rank_override is null.
        """
        stmt = (
            select(EventProduct, Product.tier_rank)
            .join(Product, Product.id == EventProduct.product_id)
            .where(EventProduct.tenant_id == tenant_id)
            .where(EventProduct.event_id == event_id)
            .order_by(EventProduct.created_at.asc())
        )
        if bar_id is not None:
            stmt = stmt.where(EventProduct.bar_id == bar_id)
        if only_available:
            stmt = stmt.where(EventProduct.is_available.is_(True))
        result = await self.db.execute(stmt)
        return result.all()

    async def get_by_id(
        self,
        tenant_id: UUID,
        event_product_id: UUID,
    ) -> tuple[EventProduct, int | None] | None:
        """Fetch one event_product row with its Product.tier_rank. Tenant-scoped."""
        stmt = (
            select(EventProduct, Product.tier_rank)
            .join(Product, Product.id == EventProduct.product_id)
            .where(EventProduct.id == event_product_id)
            .where(EventProduct.tenant_id == tenant_id)
        )
        result = await self.db.execute(stmt)
        row = result.first()
        return (row[0], row[1]) if row else None

    async def find_existing_triple(
        self,
        tenant_id: UUID,
        event_id: UUID,
        bar_id: UUID,
        product_id: UUID,
    ) -> EventProduct | None:
        """Return the existing row for (event, bar, product), if any.

        Used before create() to produce a friendly 409 rather than raw
        IntegrityError from the unique index.
        """
        stmt = (
            select(EventProduct)
            .where(EventProduct.tenant_id == tenant_id)
            .where(EventProduct.event_id == event_id)
            .where(EventProduct.bar_id == bar_id)
            .where(EventProduct.product_id == product_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ─── Write (service commits, repo flushes) ────────────────────────────────

    async def create(
        self,
        tenant_id: UUID,
        data: EventProductCreate,
    ) -> EventProduct:
        """Insert a new menu row. Service validates FKs + coherence first."""
        ep = EventProduct(
            tenant_id=tenant_id,
            event_id=data.event_id,
            bar_id=data.bar_id,
            product_id=data.product_id,
            price_cents=data.price_cents,
            tier_rank_override=data.tier_rank_override,
            is_available=data.is_available,
        )
        self.db.add(ep)
        await self.db.flush()
        await self.db.refresh(ep)
        return ep

    async def update(
        self,
        event_product: EventProduct,
        data: EventProductUpdate,
    ) -> EventProduct:
        """Apply a partial update. model_fields_set preserves 'explicit null'
        vs 'absent' semantics — setting tier_rank_override=null in the
        payload will clear the override (fall back to Product default).
        """
        payload = data.model_dump(exclude_unset=True)
        for field, value in payload.items():
            setattr(event_product, field, value)
        self.db.add(event_product)
        await self.db.flush()
        await self.db.refresh(event_product)
        return event_product

    async def delete(self, event_product: EventProduct) -> None:
        """Hard delete. Transaction history isn't tied to event_products rows
        (Slesh transactions reference product_id + bar_id directly), so
        deleting a menu line doesn't break historical data.
        """
        await self.db.delete(event_product)
        await self.db.flush()
