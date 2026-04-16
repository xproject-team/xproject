"""Database queries for the bar_stock module — pure data access.

Contract reference: §1.1 (4-layer architecture), §1.5 (service commits).

The service layer is responsible for all business rules:
- quantity invariants beyond what DB CHECKs cover
- allocate-or-topup branching (existing row vs. new)
- reconciliation calculations

The repo exposes generic primitives the service composes.
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bar_stock.models import BarStock


class BarStockRepository:
    """SQL operations for bar_stock."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Read ─────────────────────────────────────────────────────────────────

    async def list_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        bar_id: UUID | None = None,
    ) -> Sequence[BarStock]:
        """List all stock rows for an event, optionally scoped to a bar."""
        stmt = (
            select(BarStock)
            .where(BarStock.tenant_id == tenant_id)
            .where(BarStock.event_id == event_id)
            .order_by(BarStock.created_at.asc())
        )
        if bar_id is not None:
            stmt = stmt.where(BarStock.bar_id == bar_id)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_id(
        self,
        tenant_id: UUID,
        stock_id: UUID,
    ) -> BarStock | None:
        """Fetch one stock row, tenant-scoped."""
        stmt = (
            select(BarStock)
            .where(BarStock.id == stock_id)
            .where(BarStock.tenant_id == tenant_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_triple(
        self,
        tenant_id: UUID,
        event_id: UUID,
        bar_id: UUID,
        product_id: UUID,
    ) -> BarStock | None:
        """Lookup by (event, bar, product). Used by allocate to decide
        whether to create a new row or top up an existing one.
        """
        stmt = (
            select(BarStock)
            .where(BarStock.tenant_id == tenant_id)
            .where(BarStock.event_id == event_id)
            .where(BarStock.bar_id == bar_id)
            .where(BarStock.product_id == product_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ─── Write (service commits, repo flushes) ────────────────────────────────

    async def create(
        self,
        tenant_id: UUID,
        event_id: UUID,
        bar_id: UUID,
        product_id: UUID,
        allocated_qty: int,
        current_qty: int,
        returned_qty: int = 0,
    ) -> BarStock:
        """Insert a new stock row. Service validates quantities first."""
        stock = BarStock(
            tenant_id=tenant_id,
            event_id=event_id,
            bar_id=bar_id,
            product_id=product_id,
            allocated_qty=allocated_qty,
            current_qty=current_qty,
            returned_qty=returned_qty,
        )
        self.db.add(stock)
        await self.db.flush()
        await self.db.refresh(stock)
        return stock

    async def save(self, stock: BarStock) -> BarStock:
        """Persist modifications to an already-loaded stock row.

        Service layer mutates stock attributes directly (e.g.
        stock.current_qty -= qty) then calls save(). Repo just flushes
        and refreshes.
        """
        self.db.add(stock)
        await self.db.flush()
        await self.db.refresh(stock)
        return stock
