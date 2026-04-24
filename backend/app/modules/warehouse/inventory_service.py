"""InventoryService — read-side orchestration for the Owner dashboard.

All-read service: KPI tiles, product grid, activity feed, pending-review
queue. No mutations — mutations happen through ScanService and
InvoiceService (the write paths).

Spec: docs/warehouse-module-spec.md S3.4.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import WarehouseScan
from app.modules.warehouse.repository import (
    AllocationRepository,
    InventoryRepository,
    ScanRepository,
)
from app.modules.warehouse.schemas import (
    InventoryKpis,
    InventoryRow,
)


class InventoryService:
    """Read-only. No transactions committed — pure SELECT orchestration."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.inv_repo = InventoryRepository(db)
        self.scan_repo = ScanRepository(db)
        self.alloc_repo = AllocationRepository(db)

    # ─── KPI tile data (dashboard top strip) ─────────────────────────────────

    async def get_kpis(self, tenant_id: UUID) -> InventoryKpis:
        """4 KPI tiles per spec S3.4:
          1. total_items: distinct products with stock > 0
          2. total_quantity: sum of current_qty
          3. products_at_risk: count below low_stock_threshold
          4. active_allocations: sum reserved_qty across live/upcoming events
          5. pending_reviews: scans awaiting Owner approval
        """
        total_items = await self.inv_repo.count_total_items(tenant_id)
        total_quantity = await self.inv_repo.sum_total_quantity(tenant_id)
        products_at_risk = await self.inv_repo.count_at_risk(tenant_id)
        active_allocations = await self.alloc_repo.sum_active_reservations(tenant_id)
        pending_reviews = await self.scan_repo.count_pending_review(tenant_id)

        return InventoryKpis(
            total_items=total_items,
            total_quantity=total_quantity,
            products_at_risk=products_at_risk,
            active_allocations=active_allocations,
            pending_reviews=pending_reviews,
        )

    # ─── Product grid (dashboard main area) ─────────────────────────────────

    async def get_inventory_grid(
        self,
        tenant_id: UUID,
    ) -> list[InventoryRow]:
        """Build the product grid response.

        Combines warehouse_inventory + products + active-allocations subquery
        into per-row shape. is_at_risk is computed here (repo returns raw
        threshold; here we compare).
        """
        rows = await self.inv_repo.list_grid(tenant_id)

        result: list[InventoryRow] = []
        default_threshold = Decimal("10")

        for inv, product, allocated_qty in rows:
            threshold = inv.low_stock_threshold if inv.low_stock_threshold is not None else default_threshold
            available_qty = max(Decimal(0), Decimal(inv.current_qty) - allocated_qty)
            is_at_risk = Decimal(inv.current_qty) < threshold

            result.append(
                InventoryRow(
                    product_id=product.id,
                    product_name=product.name,
                    category=getattr(product, "category", None),
                    brand=getattr(product, "brand", None),
                    current_qty=Decimal(inv.current_qty),
                    allocated_qty=allocated_qty,
                    available_qty=available_qty,
                    low_stock_threshold=inv.low_stock_threshold,
                    is_at_risk=is_at_risk,
                    last_movement_at=inv.last_movement_at,
                )
            )

        return result

    # ─── Activity feed (dashboard side panel) ────────────────────────────────

    async def get_activity_feed(
        self,
        tenant_id: UUID,
        limit: int = 20,
    ) -> Sequence[WarehouseScan]:
        """Last N scans for the activity feed. Router converts ORM rows to
        ActivityFeedRow responses (product name + user name come from
        the eager-loaded relationships).
        """
        return await self.scan_repo.list_activity_feed(tenant_id, limit=limit)

    # ─── Pending-review queue (Owner approval screen) ───────────────────────

    async def get_pending_review_queue(
        self, tenant_id: UUID
    ) -> Sequence[WarehouseScan]:
        """All scans awaiting Owner action."""
        return await self.scan_repo.list_pending_review(tenant_id)
