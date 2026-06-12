"""Repository layer for event_storage. Pure DB I/O; no business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.event_storage.models import EventStockItem, SupplierProduct


class SupplierProductRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_sku(
        self, tenant_id: UUID, supplier_sku: str,
    ) -> SupplierProduct | None:
        stmt = (
            select(SupplierProduct)
            .where(SupplierProduct.tenant_id == tenant_id)
            .where(SupplierProduct.supplier_sku == supplier_sku)
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_for_tenant(
        self, tenant_id: UUID, category: str | None = None,
    ) -> list[SupplierProduct]:
        stmt = (
            select(SupplierProduct)
            .where(SupplierProduct.tenant_id == tenant_id)
            .order_by(SupplierProduct.category, SupplierProduct.item_name)
        )
        if category:
            stmt = stmt.where(SupplierProduct.category == category)
        return list((await self.db.execute(stmt)).scalars().all())


class EventStockItemRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_event(
        self, tenant_id: UUID, event_id: UUID,
    ) -> list[EventStockItem]:
        stmt = (
            select(EventStockItem)
            .where(EventStockItem.tenant_id == tenant_id)
            .where(EventStockItem.event_id == event_id)
            .order_by(EventStockItem.created_at)
        )
        return list((await self.db.execute(stmt)).scalars().all())
