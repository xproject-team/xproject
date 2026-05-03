"""Business logic for the stock_transactions module.

Three public methods:
    ingest_sale              — POS-driven drink sale with full cascade
    record_adjustment        — single-row manual correction
    get_reconciliation_report — per-event expected vs actual analytics

Key internal flows:

ingest_sale (the big one):
  1. Validate event/bar/product exist, product is a drink, bar in event
  2. Enforce idempotency for slesh_pos:
     - Required key
     - If (tenant, source, key) already exists -> return existing row set
       with idempotency_replay=true, NO new writes
  3. Fetch/prepare bar_stock for the drink itself (plan_parent_decrement)
  4. If drink has a recipe:
     - Fetch all recipe_items
     - For each item, fetch its bar_stock at the same bar
     - Build ingredient decrement plans
  5. In ONE db transaction:
     - Apply all stock decrements (mutating current_qty, respecting clamp)
     - Insert parent transaction + all child transactions
  6. Publish real-time event (best-effort; failure doesn't roll back writes)

Contract reference: §1.5 (service commits, repo flushes), §7.3 typed errors.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bar_stock.models import BarStock
from app.modules.bar_stock.repository import BarStockRepository
from app.modules.bars.repository import BarRepository
from app.modules.events.repository import EventRepository
from app.modules.products.models import ProductType
from app.modules.products.repository import ProductRepository
from app.modules.recipes.repository import RecipeRepository
from app.modules.bar_stock.realtime_publish import publish_stock_change
from app.modules.stock_transactions.cascade import (
    StockDecrementPlan,
    apply_plan_to_stock,
    plan_ingredient_decrement,
    plan_parent_decrement,
)
from app.modules.stock_transactions.models import (
    StockTransaction,
    TransactionSource,
)
from app.modules.stock_transactions.repository import (
    StockTransactionRepository,
)
from app.modules.stock_transactions.schemas import (
    ManualAdjustmentRequest,
    ReconciliationLine,
    ReconciliationReport,
    SaleIngestRequest,
)

logger = logging.getLogger(__name__)


# ─── Domain exceptions ────────────────────────────────────────────────────────

class EventNotFoundError(Exception):
    """event_id doesn't exist. -> 404."""


class BarNotFoundError(Exception):
    """bar_id doesn't exist. -> 404."""


class BarNotInEventError(Exception):
    """Bar exists but belongs to a different event. -> 422."""


class ProductNotFoundError(Exception):
    """product_id doesn't exist. -> 404."""


class NotADrinkError(Exception):
    """Attempted /sale with a non-drink product. -> 422."""
    def __init__(self, message: str, actual_type: str) -> None:
        super().__init__(message)
        self.actual_type = actual_type


class ProductArchivedError(Exception):
    """Attempted sale or adjustment on an archived product. -> 422."""


class MissingIdempotencyKeyError(Exception):
    """source=slesh_pos requires an idempotency key. -> 422."""


class TransactionNotFoundError(Exception):
    """Transaction id not found. -> 404."""


# ─── Sale ingestion result ────────────────────────────────────────────────────

class IngestResult:
    """Bundle returned by ingest_sale: parent + children + replay flag."""
    __slots__ = ("parent", "children", "idempotency_replay")

    def __init__(
        self,
        parent: StockTransaction,
        children: list[StockTransaction],
        idempotency_replay: bool,
    ) -> None:
        self.parent = parent
        self.children = children
        self.idempotency_replay = idempotency_replay


# ─── Service ──────────────────────────────────────────────────────────────────

class StockTransactionService:
    """All business logic for stock transactions + reconciliation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = StockTransactionRepository(db)
        self.events = EventRepository(db)
        self.bars = BarRepository(db)
        self.products = ProductRepository(db)
        self.recipes = RecipeRepository(db)
        self.bar_stock = BarStockRepository(db)

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
        event = await self.events.get_by_id(tenant_id, event_id)
        if event is None:
            raise EventNotFoundError(f"Event {event_id} not found")
        return await self.repo.list_for_event(
            tenant_id, event_id, bar_id=bar_id, source=source, limit=limit,
        )

    # ─── Sale ingestion (the big one) ────────────────────────────────────────

    async def ingest_sale(
        self,
        tenant_id: UUID,
        data: SaleIngestRequest,
    ) -> IngestResult:
        """Full cascade sale ingestion. See module docstring."""

        # 1. Idempotency short-circuit BEFORE any other work
        #    (cheapest check, fires on every Slesh retry)
        if data.source is TransactionSource.SLESH_POS:
            if not data.source_idempotency_key:
                raise MissingIdempotencyKeyError(
                    "source=slesh_pos requires source_idempotency_key"
                )
            existing = await self.repo.find_by_idempotency_key(
                tenant_id, data.source, data.source_idempotency_key,
            )
            if existing is not None:
                # Idempotent replay — return the existing parent + children
                children = await self.repo.get_children(tenant_id, existing.id)
                return IngestResult(
                    parent=existing,
                    children=list(children),
                    idempotency_replay=True,
                )

        # 2. Cross-module validation
        event = await self.events.get_by_id(tenant_id, data.event_id)
        if event is None:
            raise EventNotFoundError(f"Event {data.event_id} not found")

        bar = await self.bars.get_by_id(tenant_id, data.bar_id)
        if bar is None:
            raise BarNotFoundError(f"Bar {data.bar_id} not found")
        if bar.event_id != data.event_id:
            raise BarNotInEventError(
                f"Bar {data.bar_id} belongs to a different event"
            )

        product = await self.products.get_by_id(tenant_id, data.product_id)
        if product is None:
            raise ProductNotFoundError(f"Product {data.product_id} not found")
        if product.is_archived:
            raise ProductArchivedError(
                f"Product '{product.name}' is archived and cannot be sold"
            )
        if product.product_type is not ProductType.DRINK:
            raise NotADrinkError(
                f"Product '{product.name}' is a {product.product_type.value}, "
                f"not a drink. /sale accepts only drinks. "
                f"Use /adjustment for non-drink stock changes.",
                actual_type=product.product_type.value,
            )

        # 3. Plan the parent decrement against the drink's bar_stock
        drink_stock = await self.bar_stock.find_by_triple(
            tenant_id, data.event_id, data.bar_id, data.product_id,
        )
        parent_plan = plan_parent_decrement(
            drink_stock, product_id=data.product_id, qty=data.qty,
        )

        # 4. Plan ingredient decrements if the drink has a recipe
        recipe = await self.recipes.get_by_drink_product_id(
            tenant_id, data.product_id,
        )
        ingredient_plans: list[tuple[StockDecrementPlan, BarStock | None]] = []
        if recipe is not None:
            for item in recipe.items:
                ing_stock = await self.bar_stock.find_by_triple(
                    tenant_id, data.event_id, data.bar_id,
                    item.ingredient_product_id,
                )
                plan = plan_ingredient_decrement(
                    ing_stock, item, sold_qty=data.qty,
                )
                ingredient_plans.append((plan, ing_stock))

        # 5. Apply all stock decrements
        apply_plan_to_stock(drink_stock, parent_plan)
        if drink_stock is not None:
            self.db.add(drink_stock)
        for plan, stock in ingredient_plans:
            apply_plan_to_stock(stock, plan)
            if stock is not None:
                self.db.add(stock)

        # 6. Build + insert parent tx
        parent_tx = self.repo.build(
            tenant_id=tenant_id,
            event_id=data.event_id,
            bar_id=data.bar_id,
            product_id=data.product_id,
            bar_stock_id=parent_plan.bar_stock_id,
            qty=parent_plan.requested_qty,
            deficit_qty=parent_plan.deficit_qty,
            price_cents=data.price_cents,
            source=data.source,
            source_idempotency_key=data.source_idempotency_key,
            parent_transaction_id=None,  # parent itself
            note=data.note,
            payment_type=data.payment_type,
        )
        await self.repo.insert(parent_tx)

        # 7. Build + insert child txs (after parent has an id)
        children: list[StockTransaction] = []
        for plan, _stock in ingredient_plans:
            child_tx = self.repo.build(
                tenant_id=tenant_id,
                event_id=data.event_id,
                bar_id=data.bar_id,
                product_id=plan.product_id,
                bar_stock_id=plan.bar_stock_id,
                qty=plan.requested_qty,
                deficit_qty=plan.deficit_qty,
                price_cents=None,  # children don't carry revenue
                source=data.source,
                source_idempotency_key=None,  # only parent carries the key
                parent_transaction_id=parent_tx.id,
                note=None,
                payment_type=data.payment_type,
            )
            children.append(child_tx)
        if children:
            await self.repo.insert_many(children)

        # 8. Caller is responsible for the commit boundary.
        #    Router commits per HTTP request; slesh_poller commits per
        #    poll cycle (covers many ingests + cursor advance atomically).
        #    Removing the commit here unblocks batch ingestion: SQLAlchemy
        #    no longer expires identity-map objects between cart lines,
        #    eliminating the O(N^2) re-lookup loop seen during B7 backfill.

        # 9. Best-effort real-time publishing (failure shouldn't roll back)
        await self._publish_sale_event(tenant_id, data, parent_tx, children)

        return IngestResult(
            parent=parent_tx,
            children=children,
            idempotency_replay=False,
        )

    # ─── Manual adjustment ────────────────────────────────────────────────────

    async def record_adjustment(
        self,
        tenant_id: UUID,
        data: ManualAdjustmentRequest,
    ) -> StockTransaction:
        """Write a single standalone ledger row. No cascade.

        For breakage, spillage, comped drinks, reconciliation corrections.
        Uses the same clamp-at-0 policy as sales.
        """
        # Validation
        event = await self.events.get_by_id(tenant_id, data.event_id)
        if event is None:
            raise EventNotFoundError(f"Event {data.event_id} not found")

        bar = await self.bars.get_by_id(tenant_id, data.bar_id)
        if bar is None:
            raise BarNotFoundError(f"Bar {data.bar_id} not found")
        if bar.event_id != data.event_id:
            raise BarNotInEventError(
                f"Bar {data.bar_id} belongs to a different event"
            )

        product = await self.products.get_by_id(tenant_id, data.product_id)
        if product is None:
            raise ProductNotFoundError(f"Product {data.product_id} not found")
        if product.is_archived:
            raise ProductArchivedError(
                f"Product '{product.name}' is archived"
            )

        # Plan + apply (reusing the parent-decrement logic for clamping)
        stock = await self.bar_stock.find_by_triple(
            tenant_id, data.event_id, data.bar_id, data.product_id,
        )
        plan = plan_parent_decrement(stock, data.product_id, data.qty)
        apply_plan_to_stock(stock, plan)
        if stock is not None:
            self.db.add(stock)

        tx = self.repo.build(
            tenant_id=tenant_id,
            event_id=data.event_id,
            bar_id=data.bar_id,
            product_id=data.product_id,
            bar_stock_id=plan.bar_stock_id,
            qty=plan.requested_qty,
            deficit_qty=plan.deficit_qty,
            price_cents=None,
            source=data.source,
            source_idempotency_key=None,
            parent_transaction_id=None,
            note=data.note,
        )
        await self.repo.insert(tx)
        await self.db.commit()
        await publish_stock_change(
            tenant_id=tx.tenant_id,
            event_id=tx.event_id,
            bar_id=tx.bar_id,
            product_id=tx.product_id,
            change_type="adjustment",
            extra={
                "qty": str(tx.qty),
                "source": tx.source.value if hasattr(tx.source, "value") else str(tx.source),
            },
        )
        return tx

    # ─── Reconciliation ───────────────────────────────────────────────────────

    async def get_reconciliation_report(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> ReconciliationReport:
        """Compute per-bar_stock expected vs actual depletion for an event.

        For each bar_stock row at the event:
            expected = allocated - current - returned    (accounting-side)
            actual   = SUM(tx.qty - tx.deficit_qty)      (ledger-side)
            anomaly  = actual - expected

        Anomaly is signed: positive = more consumed than accounting shows
        (shrinkage/free pours), negative = less (un-rung sales, count error).
        """
        # 1. Event exists?
        event = await self.events.get_by_id(tenant_id, event_id)
        if event is None:
            raise EventNotFoundError(f"Event {event_id} not found")

        # 2. Fetch all bar_stock rows for this event (the universe of
        #    things to reconcile)
        stock_rows = await self.bar_stock.list_for_event(tenant_id, event_id)

        # 3. Fetch per-bar_stock actual consumption from the ledger
        actual_by_stock = await self.repo.actual_consumption_by_bar_stock(
            tenant_id, event_id,
        )

        # 4. Build report lines
        lines: list[ReconciliationLine] = []
        for stock in stock_rows:
            expected = Decimal(
                stock.allocated_qty - stock.current_qty - stock.returned_qty,
            )
            actual = actual_by_stock.get(stock.id, Decimal("0"))
            anomaly = actual - expected
            lines.append(
                ReconciliationLine(
                    bar_id=stock.bar_id,
                    product_id=stock.product_id,
                    bar_stock_id=stock.id,
                    allocated_qty=stock.allocated_qty,
                    current_qty=stock.current_qty,
                    returned_qty=stock.returned_qty,
                    expected_consumption=expected,
                    actual_consumption=actual,
                    anomaly_qty=anomaly,
                )
            )

        # 5. Header aggregates
        total_revenue = await self.repo.revenue_for_event(tenant_id, event_id)
        tx_count = await self.repo.transaction_count_for_event(
            tenant_id, event_id,
        )
        anomaly_count = sum(1 for line in lines if line.anomaly_qty != 0)

        return ReconciliationReport(
            event_id=event_id,
            generated_at=datetime.now(UTC),
            total_revenue_cents=total_revenue,
            transaction_count=tx_count,
            lines=lines,
            anomaly_count=anomaly_count,
        )

    # ─── Real-time publishing (best-effort) ──────────────────────────────────

    async def _publish_sale_event(
        self,
        tenant_id: UUID,
        data: SaleIngestRequest,
        parent: StockTransaction,
        children: list[StockTransaction],
    ) -> None:
        """Fire a WebSocket event so Dashboard tiles refresh in real time.

        Wrapped in try/except so a broker hiccup can't roll back the ledger.
        """
        try:
            from app.realtime.publisher import publish_event
        except ImportError:
            logger.debug("realtime publisher unavailable; skipping publish")
            return

        try:
            await publish_event(
                channel=f"event:{data.event_id}",
                payload={
                    "type": "sale.ingested",
                    "tenant_id": str(tenant_id),
                    "event_id": str(data.event_id),
                    "bar_id": str(data.bar_id),
                    "product_id": str(data.product_id),
                    "parent_transaction_id": str(parent.id),
                    "child_count": len(children),
                    "qty": float(parent.qty),
                    "price_cents": parent.price_cents,
                    "deficit_qty": float(parent.deficit_qty),
                    "created_at": parent.created_at.isoformat()
                    if parent.created_at else None,
                },
            )
        except Exception as e:  # noqa: BLE001 — broad catch is deliberate here
            logger.warning(
                "failed to publish sale event (ledger was written OK): %s", e,
            )

    async def compute_burn_rates(self, tenant_id, event_id, bar_id=None):
        """Per-product burn rate with adaptive 30/60/120/full-event window."""
        from sqlalchemy import and_, select, func
        from datetime import timedelta
        from app.modules.stock_transactions.models import StockTransaction
        from app.modules.bar_stock.models import BarStock
        now = datetime.now(UTC)
        event = await self.events.get_by_id(tenant_id, event_id)
        if event is None: return []
        event_start = getattr(event, "started_at", None) or event.created_at
        base = [StockTransaction.tenant_id==tenant_id, StockTransaction.event_id==event_id, StockTransaction.parent_transaction_id.is_not(None)]
        if bar_id is not None: base.append(StockTransaction.bar_id==bar_id)
        full_stmt = select(StockTransaction.product_id, StockTransaction.bar_id).where(and_(*base)).group_by(StockTransaction.product_id, StockTransaction.bar_id)
        pairs = (await self.db.execute(full_stmt)).all()
        out = []
        for pid, bid in pairs:
            window_min, consumed = None, Decimal("0")
            for wmin in (30, 60, 120):
                ws = now - timedelta(minutes=wmin)
                v = (await self.db.execute(select(func.sum(StockTransaction.qty - StockTransaction.deficit_qty)).where(and_(*base, StockTransaction.product_id==pid, StockTransaction.bar_id==bid, StockTransaction.created_at>=ws)))).scalar()
                if v and v > 0: window_min, consumed = wmin, v; break
            if window_min is None:
                window_min = max(int((now-event_start).total_seconds()/60), 1)
                consumed = (await self.db.execute(select(func.sum(StockTransaction.qty - StockTransaction.deficit_qty)).where(and_(*base, StockTransaction.product_id==pid, StockTransaction.bar_id==bid)))).scalar() or Decimal("0")
            rate = consumed / (Decimal(window_min)/Decimal(60)) if window_min > 0 else Decimal("0")
            cq = (await self.db.execute(select(BarStock.current_qty).where(and_(BarStock.tenant_id==tenant_id, BarStock.event_id==event_id, BarStock.bar_id==bid, BarStock.product_id==pid)))).scalar()
            ttd = (Decimal(cq)/rate)*Decimal(60) if cq is not None and rate > 0 else None
            from decimal import ROUND_HALF_UP; q2=Decimal("0.01"); def_round=lambda v: v.quantize(q2, rounding=ROUND_HALF_UP) if isinstance(v, Decimal) else v; label = ("last_30m" if window_min==30 else "last_60m" if window_min==60 else "last_120m" if window_min==120 else "event_wide"); out.append({"product_id": pid, "bar_id": bid, "window_minutes": window_min, "window_label": label, "actual_consumed": def_round(consumed), "burn_rate_per_hour": def_round(rate), "current_qty": cq, "time_to_depletion_min": def_round(ttd)})
        return out

    async def compute_burn_rate_fixed_window(
        self,
        tenant_id,
        event_id,
        window_minutes: int,
        bar_id=None,
    ):
        """Per-product burn rate over a FIXED window (no adaptive fallback).

        Used by anomaly detectors that need to compare rates across two
        specific time windows (e.g. demand-spike = 15min vs 60min). Always
        returns one row per (product, bar) pair that has at least one
        transaction in the event, even if the fixed window saw zero activity
        (rate=0 in that case, so callers can still compare ratios cleanly).
        """
        from sqlalchemy import and_, select, func
        from datetime import timedelta
        from app.modules.stock_transactions.models import StockTransaction

        now = datetime.now(UTC)
        window_start = now - timedelta(minutes=window_minutes)

        base = [
            StockTransaction.tenant_id == tenant_id,
            StockTransaction.event_id == event_id,
            StockTransaction.parent_transaction_id.is_not(None),
        ]
        if bar_id is not None:
            base.append(StockTransaction.bar_id == bar_id)

        pairs_stmt = (
            select(StockTransaction.product_id, StockTransaction.bar_id)
            .where(and_(*base))
            .group_by(StockTransaction.product_id, StockTransaction.bar_id)
        )
        pairs = (await self.db.execute(pairs_stmt)).all()

        out = []
        for pid, bid in pairs:
            consumed = (await self.db.execute(
                select(func.sum(StockTransaction.qty - StockTransaction.deficit_qty))
                .where(and_(
                    *base,
                    StockTransaction.product_id == pid,
                    StockTransaction.bar_id == bid,
                    StockTransaction.created_at >= window_start,
                ))
            )).scalar() or Decimal("0")
            hours = Decimal(window_minutes) / Decimal(60)
            rate = consumed / hours if hours > 0 else Decimal("0")
            from decimal import ROUND_HALF_UP
            q2 = Decimal("0.01")
            def_round = lambda v: v.quantize(q2, rounding=ROUND_HALF_UP) if isinstance(v, Decimal) else v
            out.append({
                "product_id": pid,
                "bar_id": bid,
                "window_minutes": window_minutes,
                "actual_consumed": def_round(consumed),
                "burn_rate_per_hour": def_round(rate),
            })
        return out

