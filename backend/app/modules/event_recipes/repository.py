"""Database queries for the event_recipes module — pure data access.

Contract reference: see app/modules/venues/repository.py for the
4-layer convention (repo flushes, service commits).
"""
from decimal import Decimal
from typing import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models import Bar
from app.modules.event_storage.models import EventCategoryIngredient, SupplierProduct
from app.modules.event_recipes.schemas import EventRecipeCreate, EventRecipePatch


class EventRecipeRepository:
    """Handles all SQL operations for EventCategoryIngredient records."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(
        self, tenant_id: UUID, row_id: UUID,
    ) -> EventCategoryIngredient | None:
        stmt = select(EventCategoryIngredient).where(
            EventCategoryIngredient.id == row_id,
            EventCategoryIngredient.tenant_id == tenant_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_bar(
        self, tenant_id: UUID, event_id: UUID, bar_id: UUID,
    ) -> Bar | None:
        """Bar must belong to the same event the recipe row is for."""
        stmt = select(Bar).where(
            Bar.id == bar_id,
            Bar.tenant_id == tenant_id,
            Bar.event_id == event_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_supplier_product(
        self, tenant_id: UUID, supplier_product_id: UUID,
    ) -> SupplierProduct | None:
        """supplier_products are tenant-wide (not per-event)."""
        stmt = select(SupplierProduct).where(
            SupplierProduct.id == supplier_product_id,
            SupplierProduct.tenant_id == tenant_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def exists(
        self,
        tenant_id: UUID,
        event_id: UUID,
        drink_name: str,
        bar_id: UUID,
        supplier_product_id: UUID,
    ) -> bool:
        """Idempotency guard for the single-row POST — matches the
        (event_id, drink_name, bar_id, supplier_product_id) key."""
        stmt = select(EventCategoryIngredient.id).where(
            EventCategoryIngredient.tenant_id == tenant_id,
            EventCategoryIngredient.event_id == event_id,
            func.lower(EventCategoryIngredient.slesh_category) == drink_name.strip().lower(),
            EventCategoryIngredient.bar_id == bar_id,
            EventCategoryIngredient.supplier_product_id == supplier_product_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def existing_keys(
        self, tenant_id: UUID, event_id: UUID,
    ) -> set[tuple[str, UUID, UUID]]:
        """All (drink_name.lower(), bar_id, supplier_product_id) keys
        already on this event — used by the bulk endpoint to reject
        duplicates without one query per row."""
        stmt = select(
            EventCategoryIngredient.slesh_category,
            EventCategoryIngredient.bar_id,
            EventCategoryIngredient.supplier_product_id,
        ).where(
            EventCategoryIngredient.tenant_id == tenant_id,
            EventCategoryIngredient.event_id == event_id,
        )
        result = await self.db.execute(stmt)
        return {
            (r.slesh_category.strip().lower(), r.bar_id, r.supplier_product_id)
            for r in result.all()
        }

    async def create(
        self, tenant_id: UUID, data: EventRecipeCreate,
    ) -> EventCategoryIngredient:
        """Insert a new row. Flushes to assign id; service owns commit."""
        row = EventCategoryIngredient(
            tenant_id=tenant_id,
            event_id=data.event_id,
            slesh_category=data.drink_name.strip(),
            bar_id=data.bar_id,
            supplier_product_id=data.supplier_product_id,
            ml_per_sale=Decimal(str(data.ml_per_sale)),
            is_optional=data.is_optional,
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update(
        self, row: EventCategoryIngredient, patch: EventRecipePatch,
    ) -> EventCategoryIngredient:
        if patch.ml_per_sale is not None:
            row.ml_per_sale = Decimal(str(patch.ml_per_sale))
        if patch.is_optional is not None:
            row.is_optional = patch.is_optional
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def delete(self, row: EventCategoryIngredient) -> None:
        await self.db.delete(row)
        await self.db.flush()

    async def list_for_event(
        self, tenant_id: UUID, event_id: UUID,
    ) -> Sequence:
        """Joined rows for GET /event-recipes/{event_id}. Outer-joins Bar
        since bar_id can be NULL on legacy rows (see schemas.py note);
        inner-joins SupplierProduct since it's always required."""
        stmt = (
            select(
                EventCategoryIngredient.id,
                EventCategoryIngredient.event_id,
                EventCategoryIngredient.slesh_category,
                EventCategoryIngredient.bar_id,
                Bar.name.label("bar_name"),
                EventCategoryIngredient.supplier_product_id,
                SupplierProduct.item_name.label("supplier_product_name"),
                EventCategoryIngredient.ml_per_sale,
                EventCategoryIngredient.is_optional,
            )
            .select_from(EventCategoryIngredient)
            .outerjoin(Bar, Bar.id == EventCategoryIngredient.bar_id)
            .join(
                SupplierProduct,
                SupplierProduct.id == EventCategoryIngredient.supplier_product_id,
            )
            .where(
                EventCategoryIngredient.tenant_id == tenant_id,
                EventCategoryIngredient.event_id == event_id,
            )
            .order_by(
                EventCategoryIngredient.slesh_category,
                Bar.name,
                EventCategoryIngredient.is_optional.asc(),
                SupplierProduct.item_name,
            )
        )
        result = await self.db.execute(stmt)
        return result.all()
