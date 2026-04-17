"""Database queries for the stock_transactions module.

Contract reference: §1.1 (4-layer) + §1.5 (service commits).

Scope:
- Append-only writes: insert_transaction + insert_many
- Idempotency lookup: find_by_idempotency_key
- List / get for history queries
- Aggregation primitives for reconciliation: revenue_for_event,
  actual_consumption_by_bar_stock

The repo NEVER updates or deletes transactions — that's append-only.
"""
from decimal import Decimal
from typing import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.stock_transactions.models import (
    StockTransaction,
    TransactionSource,
)


class StockTransactionRepository:
    """SQL operations for stock_transactions."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Reads ────────────────────────────────────────────────────────────────

    async def list_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        bar_id: UUID | None = None,
        source: TransactionSource | None = None,
        limit: int = 500,
    ) -> Sequence[StockTransaction]:
        """List transactions for an event, newest first, capped at limit."""
        stmt = (
            select(StockTransaction)
            .where(StockTransaction.tenant_id == tenant_id)
            .where(StockTransaction.event_id == event_id)
            .order_by(StockTransaction.created_at.desc())
            .limit(limit)
        )
        if bar_id is not None:
            stmt = stmt.where(StockTransaction.bar_id == bar_id)
        if source is not None:
            stmt = stmt.where(StockTransaction.source == source)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_id(
        self,
        tenant_id: UUID,
        transaction_id: UUID,
    ) -> StockTransaction | None:
        stmt = (
            select(StockTransaction)
            .where(StockTransaction.id == transaction_id)
            .where(StockTransaction.tenant_id == tenant_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_children(
        self,
        tenant_id: UUID,
        parent_id: UUID,
    ) -> Sequence[StockTransaction]:
        """Fetch all child rows for a parent (the ingredient lines of a sale)."""
        stmt = (
            select(StockTransaction)
            .where(StockTransaction.tenant_id == tenant_id)
            .where(StockTransaction.parent_transaction_id == parent_id)
            .order_by(StockTransaction.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def find_by_idempotency_key(
        self,
        tenant_id: UUID,
        source: TransactionSource,
        key: str,
    ) -> StockTransaction | None:
        """Return the existing transaction with this (tenant, source, key)
        triple, if any. Used by service before creating a POS sale to honor
        idempotent replays."""
        stmt = (
            select(StockTransaction)
            .where(StockTransaction.tenant_id == tenant_id)
            .where(StockTransaction.source == source)
            .where(StockTransaction.source_idempotency_key == key)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ─── Append-only writes ───────────────────────────────────────────────────

    def build(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        bar_id: UUID,
        product_id: UUID,
        bar_stock_id: UUID | None,
        qty: Decimal,
        deficit_qty: Decimal,
        price_cents: int | None,
        source: TransactionSource,
        source_idempotency_key: str | None,
        parent_transaction_id: UUID | None,
        note: str | None,
    ) -> StockTransaction:
        """Build (but don't persist) a StockTransaction. Service uses this
        to construct the parent + children set, then flush them together."""
        return StockTransaction(
            tenant_id=tenant_id,
            event_id=event_id,
            bar_id=bar_id,
            product_id=product_id,
            bar_stock_id=bar_stock_id,
            qty=qty,
            deficit_qty=deficit_qty,
            price_cents=price_cents,
            source=source,
            source_idempotency_key=source_idempotency_key,
            parent_transaction_id=parent_transaction_id,
            note=note,
        )

    async def insert(self, tx: StockTransaction) -> StockTransaction:
        """Insert and flush. Service commits at the outer boundary."""
        self.db.add(tx)
        await self.db.flush()
        await self.db.refresh(tx)
        return tx

    async def insert_many(
        self,
        txs: list[StockTransaction],
    ) -> list[StockTransaction]:
        """Insert a parent + all children in one flush.

        The order is important: the parent tx must be flushed FIRST so its
        id is available to set on the children's parent_transaction_id.
        Service is responsible for ordering txs[0] = parent.
        """
        for tx in txs:
            self.db.add(tx)
        await self.db.flush()
        for tx in txs:
            await self.db.refresh(tx)
        return txs

    # ─── Reconciliation aggregations ──────────────────────────────────────────

    async def revenue_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> int:
        """Total revenue in cents across all PARENT transactions for an event.

        Parents carry price_cents; children don't. We sum only rows with
        non-null price_cents to avoid double-counting ingredient rows.
        """
        stmt = (
            select(func.coalesce(func.sum(StockTransaction.price_cents), 0))
            .where(StockTransaction.tenant_id == tenant_id)
            .where(StockTransaction.event_id == event_id)
            .where(StockTransaction.price_cents.is_not(None))
        )
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    async def actual_consumption_by_bar_stock(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> dict[UUID, Decimal]:
        """Map bar_stock_id -> SUM(qty - deficit_qty) for an event.

        Used by reconciliation to compute ACTUAL depletion per stock row.
        (qty - deficit_qty) is the portion that actually moved bar_stock;
        deficit_qty is the portion we couldn't deduct because stock was at 0.

        Rows with bar_stock_id=NULL are skipped (no stock row to reconcile
        against — those are pure analytics signals).
        """
        stmt = (
            select(
                StockTransaction.bar_stock_id,
                func.coalesce(
                    func.sum(StockTransaction.qty - StockTransaction.deficit_qty),
                    0,
                ),
            )
            .where(StockTransaction.tenant_id == tenant_id)
            .where(StockTransaction.event_id == event_id)
            .where(StockTransaction.bar_stock_id.is_not(None))
            .group_by(StockTransaction.bar_stock_id)
        )
        result = await self.db.execute(stmt)
        return {row[0]: Decimal(row[1]) for row in result.all()}

    async def transaction_count_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> int:
        """Total number of transactions (parent + children) for an event.

        Used in the reconciliation report header. Includes manual
        adjustments and reconciliation corrections.
        """
        stmt = (
            select(func.count(StockTransaction.id))
            .where(StockTransaction.tenant_id == tenant_id)
            .where(StockTransaction.event_id == event_id)
        )
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)
