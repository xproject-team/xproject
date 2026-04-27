"""Report aggregation service — turns a completed event into ReportData.

Given a tenant_id + event_id, this service computes every number the report
will display: revenue KPIs, per-bar breakdowns, stock opening/closing rows,
and the alert timeline. The output is a fully-populated ReportData object
EXCEPT for the `narrative` field — that's the NarrativeEngine's job (Phase
1.5). The aggregator stays pure: it reads, it computes, it returns. No
persistence, no side effects.

Design decisions (locked in 2026-04-22 planning):
  - Revenue = sales only: sources 'slesh_pos' + 'manual_bartender'.
    Reconciliation corrections and manual_adjustment are NOT revenue.
  - Stock-out detection = heuristic (current_qty == 0). 90% accurate, fast.
    Rigorous timeline scan is a v1.1 upgrade if the narrative needs the
    exact stock-out minute.
  - bar_stock is the source of truth for opening/closing/consumed:
      consumed = allocated_qty - current_qty - returned_qty
    Math is pre-maintained by the stock_transactions module; we don't
    re-derive it from stock_transactions SUMs.

Spec: docs/report-module-spec.md §3 + §4.2.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.models import Alert
from app.modules.auth.models import User
from app.modules.bar_stock.models import BarStock
from app.modules.bars.models import Bar
from app.modules.events.models import Event
from app.modules.products.models import Product
from app.modules.reports.schemas import (
    ReportAlertRow,
    ReportBarRevenue,
    ReportData,
    ReportEventInfo,
    ReportNarrative,
    ReportRevenueKpis,
    ReportStockRow,
)
from app.modules.stock_transactions.models import StockTransaction, TransactionSource
from app.modules.venues.models import Venue


# Transaction sources that count as revenue. Adjustments and reconciliations
# are housekeeping, not customer spend.
REVENUE_SOURCES = ("slesh_pos", "manual_bartender")


class EventNotFoundForReportError(Exception):
    """Raised when the aggregator is asked about an event that doesn't exist
    for this tenant. Service layer maps this to HTTP 404."""


class EventNotCompletedError(Exception):
    """Raised when aggregation is requested for an event that hasn't ended.
    The report contract requires a final state."""


class ReportAggregator:
    """Computes ReportData for a single event.

    Public API is one method: `aggregate(tenant_id, event_id) -> ReportData`.
    Helper methods are private — they each build one slice of the snapshot.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Public entry point ──────────────────────────────────────────────────

    async def aggregate(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        report_id: UUID,
        version: int,
        language: str,
        generated_at,
    ) -> ReportData:
        """Build a complete ReportData snapshot for the given event.

        Raises:
          EventNotFoundForReportError: event doesn't exist for this tenant.
          EventNotCompletedError: event is not in COMPLETED status with
            a populated ended_at timestamp.
        """
        event = await self._load_event(tenant_id, event_id)
        if event is None:
            raise EventNotFoundForReportError(
                f"Event {event_id} not found for tenant {tenant_id}"
            )
        if event.ended_at is None or event.started_at is None:
            raise EventNotCompletedError(
                f"Event {event_id} has no started_at/ended_at — cannot aggregate"
            )

        # Empty narrative placeholder — Phase 1.5 fills this.
        narrative = ReportNarrative(
            what_happened="",
            what_worked="",
            what_next=[],
        )

        event_info = await self._build_event_info(event)
        revenue_kpis = await self._build_revenue_kpis(
            tenant_id, event_id, event_info.duration_hours
        )
        bar_revenues = await self._build_bar_revenues(tenant_id, event_id)
        stock_rows = await self._build_stock_rows(
            tenant_id, event_id, event_info.duration_hours
        )
        alerts = await self._build_alerts(tenant_id, event_id)

        return ReportData(
            report_id=report_id,
            version=version,
            language=language,
            generated_at=generated_at,
            event=event_info,
            revenue_kpis=revenue_kpis,
            bar_revenues=bar_revenues,
            stock_rows=stock_rows,
            alerts=alerts,
            narrative=narrative,
        )

    # ─── Slice 1: event metadata ─────────────────────────────────────────────

    async def _load_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> Event | None:
        stmt = (
            select(Event)
            .where(
                Event.tenant_id == tenant_id,
                Event.id == event_id,
            )
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _build_event_info(self, event: Event) -> ReportEventInfo:
        """ReportEventInfo: cover-page identity + timing."""
        # Venue name for the cover page.
        venue_name_stmt = select(Venue.name).where(Venue.id == event.venue_id)
        venue_name = (await self.db.execute(venue_name_stmt)).scalar_one_or_none() or "—"

        # Count active bars for this event. Inactive/soft-deleted bars excluded.
        bars_count_stmt = (
            select(func.count(Bar.id))
            .where(
                Bar.tenant_id == event.tenant_id,
                Bar.event_id == event.id,
                Bar.is_active.is_(True),
            )
        )
        bars_count = (await self.db.execute(bars_count_stmt)).scalar_one() or 0

        duration_seconds = (event.ended_at - event.started_at).total_seconds()
        duration_hours = round(duration_seconds / 3600.0, 2)

        return ReportEventInfo(
            event_id=event.id,
            event_name=event.name,
            venue_name=venue_name,
            started_at=event.started_at,
            ended_at=event.ended_at,
            duration_hours=duration_hours,
            bars_count=int(bars_count),
            guests_served=None,  # ticketing integration → v1.2
            expected_guest_count=event.expected_guest_count,
        )

    # ─── Slice 2: revenue KPIs ───────────────────────────────────────────────

    async def _build_revenue_kpis(
        self,
        tenant_id: UUID,
        event_id: UUID,
        duration_hours: float,
    ) -> ReportRevenueKpis:
        """ReportRevenueKpis: total revenue, per-hour, peak window, top product."""
        # Base predicate: all revenue-counting transactions for this event.
        revenue_filter = and_(
            StockTransaction.tenant_id == tenant_id,
            StockTransaction.event_id == event_id,
            StockTransaction.source.in_(REVENUE_SOURCES),
            StockTransaction.price_cents.is_not(None),
        )

        # total_revenue: SUM(qty * price_cents) / 100, as Decimal.
        # qty is NUMERIC(12,3), price_cents is INTEGER. Product is Decimal.
        total_cents_expr = func.sum(
            StockTransaction.qty * StockTransaction.price_cents
        )
        total_cents_stmt = select(func.coalesce(total_cents_expr, 0)).where(revenue_filter)
        total_cents = (await self.db.execute(total_cents_stmt)).scalar_one()
        total_revenue = (Decimal(total_cents) / Decimal(100)) if total_cents else Decimal(0)

        # revenue_per_hour: simple division, avoid /0.
        revenue_per_hour = (
            total_revenue / Decimal(str(duration_hours))
            if duration_hours > 0
            else Decimal(0)
        )

        # revenue_per_bar_avg: total / (count of bars that actually sold something).
        selling_bars_stmt = (
            select(func.count(func.distinct(StockTransaction.bar_id)))
            .where(revenue_filter)
        )
        selling_bars = (await self.db.execute(selling_bars_stmt)).scalar_one() or 0
        revenue_per_bar_avg = (
            total_revenue / Decimal(selling_bars)
            if selling_bars > 0
            else Decimal(0)
        )

        # Peak hour: GROUP BY date_trunc('hour', created_at), pick highest sum.
        hour_bucket = func.date_trunc("hour", StockTransaction.created_at).label("hr")
        hour_rev = (total_cents_expr / 100.0).label("rev")
        peak_stmt = (
            select(hour_bucket, hour_rev)
            .where(revenue_filter)
            .group_by(hour_bucket)
            .order_by(desc(hour_rev))
            .limit(1)
        )
        peak_row = (await self.db.execute(peak_stmt)).first()
        peak_hour_start = peak_row[0] if peak_row else None
        peak_hour_revenue = (
            Decimal(str(peak_row[1])) if peak_row and peak_row[1] is not None else None
        )

        # Top product by units sold.
        top_stmt = (
            select(
                Product.name,
                func.sum(StockTransaction.qty).label("units"),
            )
            .join(Product, Product.id == StockTransaction.product_id)
            .where(revenue_filter)
            .group_by(Product.id, Product.name)
            .order_by(desc("units"))
            .limit(1)
        )
        top_row = (await self.db.execute(top_stmt)).first()
        top_product_name = top_row[0] if top_row else None
        top_product_units = int(top_row[1]) if top_row and top_row[1] is not None else None

        return ReportRevenueKpis(
            total_revenue=total_revenue,
            revenue_per_hour=revenue_per_hour,
            revenue_per_bar_avg=revenue_per_bar_avg,
            top_product_name=top_product_name,
            top_product_units=top_product_units,
            peak_hour_start=peak_hour_start,
            peak_hour_revenue=peak_hour_revenue,
        )

    # ─── Slice 3: per-bar revenue ranking ────────────────────────────────────

    async def _build_bar_revenues(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> list[ReportBarRevenue]:
        """ReportBarRevenue rows ordered by revenue DESC with rank + pct."""
        revenue_expr = (
            func.sum(StockTransaction.qty * StockTransaction.price_cents) / 100.0
        ).label("revenue")
        txn_count_expr = func.count(StockTransaction.id).label("txn_count")

        stmt = (
            select(
                Bar.id,
                Bar.name,
                revenue_expr,
                txn_count_expr,
            )
            .join(StockTransaction, StockTransaction.bar_id == Bar.id)
            .where(
                StockTransaction.tenant_id == tenant_id,
                StockTransaction.event_id == event_id,
                StockTransaction.source.in_(REVENUE_SOURCES),
                StockTransaction.price_cents.is_not(None),
            )
            .group_by(Bar.id, Bar.name)
            .order_by(desc("revenue"))
        )
        rows = (await self.db.execute(stmt)).all()

        if not rows:
            return []

        total = sum((Decimal(str(r[2])) for r in rows), start=Decimal(0))
        result: list[ReportBarRevenue] = []
        for rank, (bar_id, bar_name, revenue_val, txn_count) in enumerate(rows, start=1):
            revenue = Decimal(str(revenue_val)) if revenue_val is not None else Decimal(0)
            pct = float(revenue / total * 100) if total > 0 else 0.0
            result.append(
                ReportBarRevenue(
                    bar_id=bar_id,
                    bar_name=bar_name,
                    revenue=revenue,
                    revenue_pct=round(pct, 2),
                    transactions_count=int(txn_count or 0),
                    rank=rank,
                )
            )
        return result

    # ─── Slice 4: stock reality check ────────────────────────────────────────

    async def _build_stock_rows(
        self,
        tenant_id: UUID,
        event_id: UUID,
        duration_hours: float,
    ) -> list[ReportStockRow]:
        """ReportStockRow one per (bar, product) from bar_stock table.

        Consumed = allocated - current - returned (per stock_transactions spec).
        Burn rate = consumed / duration_hours, avoiding /0 for instant events.
        Stock-out is heuristic: current_qty == 0 flagged as TRUE (v1.0 choice).
        """
        stmt = (
            select(
                BarStock.bar_id,
                Bar.name.label("bar_name"),
                BarStock.product_id,
                Product.name.label("product_name"),
                BarStock.allocated_qty,
                BarStock.current_qty,
                BarStock.returned_qty,
            )
            .join(Bar, Bar.id == BarStock.bar_id)
            .join(Product, Product.id == BarStock.product_id)
            .where(
                BarStock.tenant_id == tenant_id,
                BarStock.event_id == event_id,
            )
            .order_by(Bar.name, Product.name)
        )
        rows = (await self.db.execute(stmt)).all()

        # Stock-out timestamp lookup. For each (bar, product) where stock
        # ended at 0, we want the moment the LAST revenue-producing scan
        # drove inventory below the line. One SQL hop per report — no N+1.
        stockout_stmt = (
            select(
                StockTransaction.bar_id,
                StockTransaction.product_id,
                func.max(StockTransaction.created_at).label("last_at"),
            )
            .where(
                StockTransaction.tenant_id == tenant_id,
                StockTransaction.event_id == event_id,
                StockTransaction.source.in_(
                    (TransactionSource.SLESH_POS, TransactionSource.MANUAL_BARTENDER)
                ),
            )
            .group_by(StockTransaction.bar_id, StockTransaction.product_id)
        )
        stockout_rows = (await self.db.execute(stockout_stmt)).all()
        stockout_map: dict[tuple[UUID, UUID], datetime] = {
            (b_id, p_id): ts for (b_id, p_id, ts) in stockout_rows
        }

        result: list[ReportStockRow] = []
        duration_decimal = Decimal(str(duration_hours)) if duration_hours > 0 else None

        for (
            bar_id,
            bar_name,
            product_id,
            product_name,
            allocated,
            current,
            returned,
        ) in rows:
            allocated_d = Decimal(allocated or 0)
            current_d = Decimal(current or 0)
            returned_d = Decimal(returned or 0)
            consumed_d = allocated_d - current_d - returned_d

            burn_rate = (
                consumed_d / duration_decimal
                if duration_decimal is not None
                else Decimal(0)
            )

            # v1.0 heuristic: stock_out_occurred = (current_qty == 0)
            stock_out = current_d == Decimal(0)

            result.append(
                ReportStockRow(
                    bar_id=bar_id,
                    bar_name=bar_name,
                    product_id=product_id,
                    product_name=product_name,
                    opening_qty=allocated_d,
                    closing_qty=current_d,
                    consumed_qty=consumed_d,
                    burn_rate_per_hour=burn_rate,
                    stock_out_occurred=stock_out,
                    stock_out_time=(
                        stockout_map.get((bar_id, product_id))
                        if stock_out
                        else None
                    ),
                    consumption_vs_plan_pct=None,  # needs expected_consumption field
                )
            )

        return result

    # ─── Slice 5: alerts timeline ────────────────────────────────────────────

    async def _build_alerts(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> list[ReportAlertRow]:
        """ReportAlertRow chronological. LEFT JOIN users for ack_by name."""
        stmt = (
            select(
                Alert.id,
                Alert.alert_type,
                Alert.severity,
                Alert.bar_id,
                Bar.name.label("bar_name"),
                Alert.title,
                Alert.owner_message,
                Alert.created_at,
                Alert.acknowledged_at,
                User.full_name.label("ack_by_name"),
                Alert.audience,
            )
            .join(Bar, Bar.id == Alert.bar_id, isouter=True)
            .join(User, User.id == Alert.acknowledged_by_user_id, isouter=True)
            .where(
                Alert.tenant_id == tenant_id,
                Alert.event_id == event_id,
            )
            .order_by(Alert.created_at.asc())
        )
        rows = (await self.db.execute(stmt)).all()

        return [
            ReportAlertRow(
                alert_id=r[0],
                alert_type=r[1],
                severity=r[2],
                bar_id=r[3],
                bar_name=r[4],
                title=r[5],
                owner_message=r[6],
                fired_at=r[7],
                acknowledged_at=r[8],
                acknowledged_by_name=r[9],
                audience=r[10],
            )
            for r in rows
        ]
