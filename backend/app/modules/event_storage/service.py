"""Business logic for event_storage. Filled out in commit 2."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.event_storage.repository import (
    EventStockItemRepository,
    SupplierProductRepository,
)


class EventStorageService:
    """Stub — repository wiring only. Bulk-upsert, summary aggregation,
    and master-list auto-create logic land in commit 2."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.supplier_products = SupplierProductRepository(db)
        self.event_stock_items = EventStockItemRepository(db)
