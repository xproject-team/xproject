"""Report aggregation service — turns a completed event into ReportData.

Given a tenant_id + event_id, this service computes every number the report
will display: revenue KPIs, per-bar breakdowns, stock opening/closing rows,
and the alert timeline. The output is a fully-populated ReportData object
EXCEPT for the `narrative` field — that's the NarrativeEngine's job (Phase
1.5). The aggregator stays pure: it reads, it computes, it returns. No
persistence, no side effects.

Design decisions (2026-04-22 planning, revenue source migrated Day 14
Aug 2026 to match the dashboard — one revenue definition platform-wide):
  - EURO figures = event_orders.fiscal_gross_cents over confirmed orders
    (see events/revenue.py): Slesh's money-of-record. Includes food
    trucks, no-recipe drinks, and orders whose POS shop isn't mapped to
    a bar yet (surfaced as unmapped_revenue); excludes deposits and
    fully-refunded orders; VAT included. Identical to the dashboard
    header (EventKpiSummaryService).
  - UNITS / per-product detail = stock_transactions rows with source in
    REVENUE_SOURCES — event_orders has no line-level product data. Unit
    figures are partial by design and never presented as summing to the
    euro total.
  - Old reports are NEVER regenerated to the new definition — frozen
    data_json stays frozen; ReportData.revenue_source labels which
    method a snapshot used.
  - Stock-out detection = heuristic (current_qty == 0). 90% accurate, fast.
    Rigorous timeline scan is a v1.1 upgrade if the narrative needs the
    exact stock-out minute.
  - bar_stock is the source of truth for opening/closing/consumed:
      consumed = allocated_qty - current_qty - returned_qty
    Math is pre-maintained by the stock_transactions module; we don't
    re-derive it from stock_transactions SUMs.

Spec: docs/report-module-spec.md §3 + §4.2; docs/revenue-calculation-bible.md.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import and_, case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.models import Alert
from app.modules.auth.models import User
from app.modules.bar_stock.models import BarStock
from app.modules.bars.models import Bar
from app.modules.customer_analytics.models import CustomerPurchase, CustomerSession
from app.modules.customer_intelligence.constants import LIGHT_SPEND_MAX_CENTS, WHALE_SPEND_MIN_CENTS
from app.modules.events.models import Event, EventOrder
from app.modules.events.revenue import REVENUE_SOURCES, confirmed_order_conditions
from app.modules.predictions.demand.loader import get_active_demand_predictor
from app.modules.predictions.demand.predictor import HOUR_GRID
from app.modules.predictions.demand.training_data import DRINK_CATEGORIES
from app.modules.products.models import Product
from app.modules.reports.models import Report
from app.modules.reports.schemas import (
    ReportAlertRow,
    ReportBarRevenue,
    ReportComparison,
    ReportComparisonMetric,
    ReportData,
    ReportEventInfo,
    ReportForecastAccuracy,
    ReportForecastHourRow,
    ReportGuestKpis,
    ReportNarrative,
    ReportProductPerformance,
    ReportProductRow,
    ReportRevenueDecomposition,
    ReportRevenueKpis,
    ReportStockRow,
)
from app.modules.stock_transactions.models import StockTransaction, TransactionSource
from app.modules.venues.models import Venue

# The date this feature shipped — guest/category/decomposition comparison
# metrics are only meaningful from here forward (see _build_comparison's
# docstring: NOT backfilled onto older reports by regenerating them).
GUEST_METRICS_AVAILABLE_FROM = "August 2026"


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

        # New sections (Reports feature improvement). Each is independently
        # gracefully-degrading — a missing data source (customer features
        # not yet populated, no trained demand model, no prior event to
        # compare against) never blocks the other four or the report as a
        # whole. See each method's own docstring for its specific
        # unavailable_reason states.
        guests = await self._build_guests(tenant_id, event_id)
        forecast_accuracy = await self._build_forecast_accuracy(tenant_id, event_id)
        revenue_decomposition = await self._build_revenue_decomposition(
            tenant_id, event, guests, revenue_kpis,
        )
        comparison = await self._build_comparison(
            tenant_id, event_id, event, language, revenue_kpis, guests,
        )
        product_performance = await self._build_product_performance(tenant_id, event_id)

        return ReportData(
            report_id=report_id,
            version=version,
            language=language,
            generated_at=generated_at,
            revenue_source="event_orders",
            event=event_info,
            revenue_kpis=revenue_kpis,
            bar_revenues=bar_revenues,
            stock_rows=stock_rows,
            alerts=alerts,
            narrative=narrative,
            guests=guests,
            forecast_accuracy=forecast_accuracy,
            comparison=comparison,
            revenue_decomposition=revenue_decomposition,
            product_performance=product_performance,
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
        """ReportRevenueKpis: total revenue, per-hour, peak window, top product.

        Euro figures from event_orders (money-of-record, same definition
        as the dashboard header — see events/revenue.py and the module
        docstring). top_product stays on stock_transactions: event_orders
        has no per-product line detail.
        """
        order_filter = and_(*confirmed_order_conditions(tenant_id, event_id))
        fiscal_sum = func.coalesce(func.sum(EventOrder.fiscal_gross_cents), 0)
        _penny = Decimal("0.01")

        total_cents = (
            await self.db.execute(select(fiscal_sum).where(order_filter))
        ).scalar_one()
        total_revenue = (Decimal(total_cents) / Decimal(100)).quantize(_penny)

        # Confirmed orders whose POS shop has no bar mapping yet — real
        # money, part of total_revenue, but unattributable to any bar.
        unmapped_cents = (
            await self.db.execute(
                select(fiscal_sum).where(order_filter, EventOrder.bar_id.is_(None))
            )
        ).scalar_one()
        unmapped_revenue = (Decimal(unmapped_cents) / Decimal(100)).quantize(_penny)

        # revenue_per_hour: simple division, avoid /0.
        revenue_per_hour = (
            total_revenue / Decimal(str(duration_hours))
            if duration_hours > 0
            else Decimal(0)
        )

        # revenue_per_bar_avg: bar-attributed revenue / bars that sold.
        # Unmapped money is excluded from BOTH sides — dividing the full
        # total by the mapped-bar count would silently smear it across
        # bars. count(distinct bar_id) skips NULLs, matching that.
        selling_bars_stmt = (
            select(func.count(func.distinct(EventOrder.bar_id))).where(order_filter)
        )
        selling_bars = (await self.db.execute(selling_bars_stmt)).scalar_one() or 0
        mapped_revenue = Decimal(total_cents - unmapped_cents) / Decimal(100)
        revenue_per_bar_avg = (
            (mapped_revenue / Decimal(selling_bars)).quantize(_penny)
            if selling_bars > 0
            else Decimal(0)
        )

        # Peak hour: GROUP BY date_trunc('hour', created_at_slesh) — the
        # TRUE order timestamp from Slesh. The old stock_transactions
        # version bucketed on created_at, which is the poller's ingestion
        # time (median lag 25–48s, documented tail 6.6h) and could name
        # the wrong hour.
        hour_bucket = func.date_trunc("hour", EventOrder.created_at_slesh).label("hr")
        hour_rev = (func.sum(EventOrder.fiscal_gross_cents) / 100.0).label("rev")
        peak_stmt = (
            select(hour_bucket, hour_rev)
            .where(order_filter)
            .group_by(hour_bucket)
            .order_by(desc(hour_rev))
            .limit(1)
        )
        peak_row = (await self.db.execute(peak_stmt)).first()
        peak_hour_start = peak_row[0] if peak_row else None
        peak_hour_revenue = (
            Decimal(str(peak_row[1])) if peak_row and peak_row[1] is not None else None
        )

        # Top product by units sold — stock_transactions line detail
        # (partial coverage by design; a units figure, never a euro total).
        line_filter = and_(
            StockTransaction.tenant_id == tenant_id,
            StockTransaction.event_id == event_id,
            StockTransaction.source.in_(REVENUE_SOURCES),
            StockTransaction.price_cents.is_not(None),
            StockTransaction.pos_line_status == "confirmed",
        )
        top_stmt = (
            select(
                Product.name,
                func.sum(StockTransaction.qty).label("units"),
            )
            .join(Product, Product.id == StockTransaction.product_id)
            .where(line_filter)
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
            unmapped_revenue=unmapped_revenue,
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
        """ReportBarRevenue rows ordered by revenue DESC with rank + pct.

        From event_orders grouped by bar (Day 14 migration). revenue_pct
        is of the FULL event total including unmapped orders, so rows sum
        below 100% when unmapped money exists — that remainder is
        ReportRevenueKpis.unmapped_revenue, shown explicitly, never
        redistributed. transactions_count counts confirmed orders.
        """
        order_filter = confirmed_order_conditions(tenant_id, event_id)
        revenue_expr = (func.sum(EventOrder.fiscal_gross_cents) / 100.0).label("revenue")
        order_count_expr = func.count(EventOrder.id).label("order_count")

        stmt = (
            select(
                Bar.id,
                Bar.name,
                revenue_expr,
                order_count_expr,
            )
            .join(EventOrder, EventOrder.bar_id == Bar.id)
            .where(*order_filter)
            .group_by(Bar.id, Bar.name)
            .order_by(desc("revenue"))
        )
        rows = (await self.db.execute(stmt)).all()

        if not rows:
            return []

        # pct denominator: the full confirmed-order total, unmapped included
        # — the same figure the cover page shows as total_revenue.
        total_cents = (
            await self.db.execute(
                select(func.coalesce(func.sum(EventOrder.fiscal_gross_cents), 0))
                .where(*order_filter)
            )
        ).scalar_one()
        total = Decimal(total_cents) / Decimal(100)

        result: list[ReportBarRevenue] = []
        for rank, (bar_id, bar_name, revenue_val, order_count) in enumerate(rows, start=1):
            revenue = Decimal(str(revenue_val)) if revenue_val is not None else Decimal(0)
            pct = float(revenue / total * 100) if total > 0 else 0.0
            result.append(
                ReportBarRevenue(
                    bar_id=bar_id,
                    bar_name=bar_name,
                    revenue=revenue,
                    revenue_pct=round(pct, 2),
                    transactions_count=int(order_count or 0),
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

    # ─── Section A: Guests ────────────────────────────────────────────────────

    async def _build_guests(self, tenant_id: UUID, event_id: UUID) -> ReportGuestKpis:
        """ReportGuestKpis, from customer_sessions (see EventService's
        _enqueue_customer_features_population -- this table is populated
        by a separate arq job triggered at the same event-completion
        moment as report generation, not always guaranteed to have run
        yet; see reports/repository.py::list_events_needing_reports for
        the ordering guarantee/hard-cutoff that bounds how long a report
        will wait for it).

        available=False (zero rows) is the normal state for an event
        whose population job hasn't finished, or ran but found nothing
        identifiable -- never treated as an error.
        """
        count_stmt = (
            select(
                func.count().label("identified_total"),
                func.count().filter(CustomerSession.is_registered.is_(True)).label("registered_count"),
                func.count().filter(CustomerSession.is_registered.is_(False)).label("guest_count"),
                func.count().filter(CustomerSession.is_registered.is_(None)).label("unknown_count"),
                func.count().filter(CustomerSession.total_spend_cents >= WHALE_SPEND_MIN_CENTS).label("whale_count"),
                func.count().filter(CustomerSession.total_spend_cents <= LIGHT_SPEND_MAX_CENTS).label("light_count"),
            )
            .where(CustomerSession.tenant_id == tenant_id, CustomerSession.event_id == event_id)
        )
        row = (await self.db.execute(count_stmt)).one()
        if not row.identified_total:
            return ReportGuestKpis(
                available=False,
                unavailable_reason="customer identity data not available for this event",
            )

        regular_count = row.identified_total - row.whale_count - row.light_count

        this_event_keys_stmt = select(CustomerSession.customer_key).where(
            CustomerSession.tenant_id == tenant_id, CustomerSession.event_id == event_id,
        )
        this_event_keys = set((await self.db.execute(this_event_keys_stmt)).scalars().all())

        # Python-side set intersection (matching customer_intelligence's
        # established pattern) rather than a SQL IN(...) with thousands of
        # values -- bounded, small-n data (a handful of events, each a few
        # thousand identified guests at most).
        other_keys_stmt = select(func.distinct(CustomerSession.customer_key)).where(
            CustomerSession.tenant_id == tenant_id, CustomerSession.event_id != event_id,
        )
        other_keys = set((await self.db.execute(other_keys_stmt)).scalars().all())
        returning_count = len(this_event_keys & other_keys)

        return ReportGuestKpis(
            available=True,
            identified_total=row.identified_total,
            registered_count=row.registered_count,
            guest_count=row.guest_count,
            unknown_count=row.unknown_count,
            whale_count=row.whale_count,
            regular_count=regular_count,
            light_count=row.light_count,
            whale_threshold_cents=WHALE_SPEND_MIN_CENTS,
            light_threshold_cents=LIGHT_SPEND_MAX_CENTS,
            returning_count=returning_count,
            new_count=row.identified_total - returning_count,
        )

    # ─── Section B: Forecast vs. Actual ──────────────────────────────────────

    async def _build_forecast_accuracy(
        self, tenant_id: UUID, event_id: UUID,
    ) -> ReportForecastAccuracy:
        """ReportForecastAccuracy, reusing the demand model's bytes-based
        loader (predictions/demand/loader.py, built for the customer-
        intelligence panel) and the same "actuals-through-h -> predict
        h+1" checkpoint protocol as
        customer_intelligence/service.py::_build_predicted_vs_actual and
        validate_demand_model.py -- replayed here for every hour of an
        already-COMPLETED event instead of a live one.

        Reads customer_purchases directly rather than re-deriving a live
        stock_transactions<->event_orders join (customer_intelligence's
        approach for a still-LIVE event, where customer_purchases may not
        exist yet) -- by report-generation time customer_purchases is the
        clean, already-categorized, already-populated source. Sums `qty`
        per line rather than counting rows -- matches
        training_data.py::build_current_grid's documented convention
        (qty is always 1 in observed production data today, but summed
        in case that changes).

        Band width: confidence_interval.half_width_pct is calibrated
        around predicted_final_total, not any one hour's incremental
        slice -- there is no separately-calibrated per-hour interval in
        this model. It is reused here as a relative uncertainty proxy
        for the hour's incremental prediction too, since both are driven
        by the same shape-fraction estimate the docstring on
        DemandPredictor.predict names as the shared driver of scarcity-
        widening. This is an approximation, not a second calibration --
        good enough for "did actual land in a plausible range," which is
        all the band-hit-rate statistic claims to be.
        """
        predictor, reason = await get_active_demand_predictor(self.db, tenant_id)
        if predictor is None:
            return ReportForecastAccuracy(available=False, unavailable_reason=reason)

        rows = (await self.db.execute(
            select(CustomerPurchase.ordered_at, CustomerPurchase.category, CustomerPurchase.qty).where(
                CustomerPurchase.tenant_id == tenant_id,
                CustomerPurchase.event_id == event_id,
                CustomerPurchase.is_deposit.is_(False),
                CustomerPurchase.category.in_(DRINK_CATEGORIES),
            )
        )).all()
        if not rows:
            return ReportForecastAccuracy(
                available=False, unavailable_reason="no drink purchase data available for this event",
            )

        first_order_at = min(r[0] for r in rows)
        grid: dict[int, float] = {}
        for ordered_at, _category, qty in rows:
            hour = int((ordered_at - first_order_at).total_seconds() // 3600)
            grid[hour] = grid.get(hour, 0.0) + float(qty or 0)
        final_hour_offset = max(grid.keys())

        def _hour_total(h: int) -> float:
            return float(grid.get(h, 0.0))

        def _cumulative_through(h: int) -> float:
            return float(sum(v for k, v in grid.items() if k <= h))

        cold_start = predictor.predict(0.0, 0.0)

        hours: list[ReportForecastHourRow] = []
        for target in HOUR_GRID:
            if target <= 0 or target > final_hour_offset:
                continue
            h_now = target - 1.0
            observed_so_far = _cumulative_through(int(h_now))
            prediction = predictor.predict(observed_so_far, h_now)
            by_bar = prediction["predicted_by_hour"].get(round(float(target), 1), {})
            predicted = sum(
                by_cat.get(cat, 0.0) for by_cat in by_bar.values() for cat in DRINK_CATEGORIES
            )
            half_width = prediction["confidence_interval"]["half_width_pct"] / 100.0
            lower = max(0.0, predicted * (1 - half_width))
            upper = predicted * (1 + half_width)
            actual = _hour_total(int(target))
            hours.append(ReportForecastHourRow(
                hour_of_event=target, predicted=round(predicted, 1), actual=actual,
                lower=round(lower, 1), upper=round(upper, 1),
                within_band=lower <= actual <= upper,
            ))

        return ReportForecastAccuracy(
            available=True,
            predicted_final_total=cold_start["predicted_final_total"],
            actual_final_total=_cumulative_through(final_hour_offset),
            hours=hours,
            band_hits=sum(1 for h in hours if h.within_band),
            band_hours_total=len(hours),
        )

    # ─── Section D: Revenue Decomposition ────────────────────────────────────

    async def _build_revenue_decomposition(
        self, tenant_id: UUID, event: Event, guests: ReportGuestKpis, revenue_kpis: ReportRevenueKpis,
    ) -> ReportRevenueDecomposition:
        """ReportRevenueDecomposition: attendance x purchase rate x
        orders/purchaser x AOV.

        estimated_attendance is event.expected_guest_count VERBATIM -- a
        planning figure set before the event, never a measured fact.
        purchase_rate_pct is therefore an estimate derived from an
        estimate, not a measured conversion rate; every surface that
        renders this (PDF, frontend, narrative) must say so explicitly,
        not just this docstring.
        """
        if not guests.available or event.expected_guest_count is None:
            return ReportRevenueDecomposition(
                available=False,
                unavailable_reason=(
                    "guest data not available for this event" if not guests.available
                    else "no expected_guest_count set for this event"
                ),
            )

        agg_stmt = select(
            func.sum(CustomerSession.order_count),
            func.sum(CustomerSession.total_spend_cents),
        ).where(CustomerSession.tenant_id == tenant_id, CustomerSession.event_id == event.id)
        total_orders, total_spend_cents = (await self.db.execute(agg_stmt)).one()
        total_orders = total_orders or 0
        total_spend_cents = total_spend_cents or 0

        purchasers = guests.identified_total
        estimated_attendance = event.expected_guest_count
        purchase_rate_pct = (
            round(100.0 * purchasers / estimated_attendance, 1) if estimated_attendance > 0 else None
        )
        orders_per_purchaser = round(total_orders / purchasers, 2) if purchasers > 0 else None
        aov_cents = round(total_spend_cents / total_orders) if total_orders > 0 else None

        implied_revenue_cents = None
        if purchase_rate_pct is not None and orders_per_purchaser is not None and aov_cents is not None:
            implied_revenue_cents = round(
                estimated_attendance * (purchase_rate_pct / 100.0) * orders_per_purchaser * aov_cents
            )

        return ReportRevenueDecomposition(
            available=True,
            estimated_attendance=estimated_attendance,
            purchasers=purchasers,
            purchase_rate_pct=purchase_rate_pct,
            orders_per_purchaser=orders_per_purchaser,
            average_order_value_cents=aov_cents,
            implied_revenue_cents=implied_revenue_cents,
            actual_revenue_cents=int(revenue_kpis.total_revenue * 100),
        )

    # ─── Section C: Event-over-Event Comparison ──────────────────────────────

    async def _build_comparison(
        self, tenant_id: UUID, event_id: UUID, event: Event, language: str,
        revenue_kpis: ReportRevenueKpis, guests: ReportGuestKpis,
    ) -> ReportComparison:
        """ReportComparison: this event vs. the previous one and vs. the
        season average, reusing the same data_json JSONB-path-extraction
        technique as repository.py's sum_lifetime_revenue/
        get_top_event_by_revenue (the Portfolio KPI strip's existing
        cross-report queries), applied per-metric instead of as a single
        lifetime sum.

        Revenue/peak-hour comparisons work for every past event (already
        in every historical data_json). Guest/decomposition comparisons
        only exist for reports generated from this feature's ship date
        forward -- deliberately NOT backfilled by regenerating older
        reports (that would risk changing numbers already shown to
        Omar). guest_metrics_available_from documents this plainly
        rather than silently showing fewer rows with no explanation.

        "Season" here means "every other ready report for this tenant to
        date" -- the same scope the Portfolio KPI strip's lifetime
        aggregates already use. There is no calendar-quarter/season
        boundary defined anywhere else in this codebase to reuse.
        """
        # Latest ready version per (event, language) — regeneration leaves
        # the superseded version at status='ready' too, so any query over
        # "all ready reports" double-counts regenerated events (C2). The
        # previous-event lookup and both season averages below all pick
        # ONE row per event via DISTINCT ON ... version DESC.
        prev_stmt = (
            select(Report.data_json, Event.name, Event.scheduled_at)
            .join(Event, Event.id == Report.event_id)
            .where(
                Report.tenant_id == tenant_id,
                Report.status == "ready",
                Report.language == language,
                Report.event_id != event_id,
                Event.scheduled_at < event.scheduled_at,
            )
            .order_by(desc(Event.scheduled_at), desc(Report.version))
            .limit(1)
        )
        prev_row = (await self.db.execute(prev_stmt)).first()

        revenue_text = Report.data_json["revenue_kpis"]["total_revenue"].astext
        revenue_numeric = func.cast(revenue_text, sa.Numeric(14, 2))
        season_sub = (
            select(
                revenue_numeric.label("revenue"),
                Report.data_json["revenue_source"].astext.label("revenue_source"),
            )
            .where(
                Report.tenant_id == tenant_id, Report.status == "ready",
                Report.language == language, Report.event_id != event_id,
            )
            .distinct(Report.event_id)
            .order_by(Report.event_id, Report.version.desc())
            .subquery()
        )
        season_stmt = select(
            func.count(),
            func.coalesce(func.avg(season_sub.c.revenue), 0),
            func.count().filter(
                season_sub.c.revenue_source.is_distinct_from("event_orders")
            ),
        )
        season_n, season_avg_revenue, season_old_method_n = (
            (await self.db.execute(season_stmt)).one()
        )

        if prev_row is None and not season_n:
            return ReportComparison(
                available=False, unavailable_reason="no prior events to compare against",
                guest_metrics_available_from=GUEST_METRICS_AVAILABLE_FROM,
            )

        # Mixed measurement basis: this report's revenue is event_orders
        # money; any compared report whose snapshot predates the Day 14
        # migration (no revenue_source marker) was measured from stock
        # movements. The delta then carries a definitional component —
        # renderers footnote it, the narrative skips its
        # revenue-vs-previous sentence.
        prev_uses_old_method = (
            prev_row is not None
            and (prev_row[0] or {}).get("revenue_source") != "event_orders"
        )
        mixed_revenue_sources = prev_uses_old_method or bool(season_old_method_n)

        metrics: list[ReportComparisonMetric] = []
        current_revenue = float(revenue_kpis.total_revenue)

        def _pct_delta(current: float, other: float | None) -> float | None:
            if other is None or other == 0:
                return None
            return round(100.0 * (current - other) / other, 1)

        prev_data = prev_row[0] if prev_row else None
        prev_revenue = (
            float(prev_data["revenue_kpis"]["total_revenue"]) if prev_data else None
        )
        metrics.append(ReportComparisonMetric(
            label="Total Revenue",
            unit="eur",
            current_value=current_revenue,
            previous_event_value=prev_revenue,
            previous_event_delta_pct=_pct_delta(current_revenue, prev_revenue),
            season_avg_value=float(season_avg_revenue) if season_n else None,
            season_avg_delta_pct=_pct_delta(current_revenue, float(season_avg_revenue) if season_n else None),
        ))

        if guests.available:
            prev_guests = (
                float(prev_data["guests"]["identified_total"])
                if prev_data and prev_data.get("guests") else None
            )
            guest_season_sub = (
                select(func.cast(
                    Report.data_json["guests"]["identified_total"].astext, sa.Numeric(10, 2),
                ).label("identified"))
                .where(
                    Report.tenant_id == tenant_id, Report.status == "ready",
                    Report.language == language, Report.event_id != event_id,
                    Report.data_json["guests"].isnot(None),
                )
                .distinct(Report.event_id)
                .order_by(Report.event_id, Report.version.desc())
                .subquery()
            )
            guest_season_stmt = select(
                func.count(),
                func.coalesce(func.avg(guest_season_sub.c.identified), 0),
            )
            guest_season_n, guest_season_avg = (await self.db.execute(guest_season_stmt)).one()
            metrics.append(ReportComparisonMetric(
                label="Identified Guests",
                unit="count",
                current_value=float(guests.identified_total),
                previous_event_value=prev_guests,
                previous_event_delta_pct=_pct_delta(float(guests.identified_total), prev_guests),
                season_avg_value=float(guest_season_avg) if guest_season_n else None,
                season_avg_delta_pct=_pct_delta(
                    float(guests.identified_total), float(guest_season_avg) if guest_season_n else None,
                ),
            ))

        return ReportComparison(
            available=True,
            previous_event_name=prev_row[1] if prev_row else None,
            previous_event_date=prev_row[2] if prev_row else None,
            season_avg_n_events=season_n or 0,
            metrics=metrics,
            guest_metrics_available_from=GUEST_METRICS_AVAILABLE_FROM,
            mixed_revenue_sources=mixed_revenue_sources,
        )

    # ─── Section E: Top and Lowest-Selling Products ──────────────────────────

    async def _build_product_performance(
        self, tenant_id: UUID, event_id: UUID,
    ) -> ReportProductPerformance:
        """ReportProductPerformance: reuses _build_revenue_kpis' top-
        product query shape (aggregator.py's original single-row LIMIT 1
        lookup), generalized to a full ranked list plus category share.

        "lowest_selling", not "bottom"/"underperforming": excludes
        products with zero units sold entirely (never listed is a
        different situation from selling weakly -- a product with zero
        sales may simply not have been on this event's menu). The
        narrative raises a lowest-selling product as a question, not a
        verdict -- see templates_next.py.
        """
        revenue_filter = and_(
            StockTransaction.tenant_id == tenant_id,
            StockTransaction.event_id == event_id,
            StockTransaction.source.in_(REVENUE_SOURCES),
            StockTransaction.price_cents.is_not(None),
            StockTransaction.pos_line_status == "confirmed",
        )
        stmt = (
            select(
                Product.id, Product.name, Product.category,
                func.sum(StockTransaction.qty).label("units"),
                (func.sum(StockTransaction.qty * StockTransaction.price_cents)).label("revenue_cents"),
            )
            .join(Product, Product.id == StockTransaction.product_id)
            .where(revenue_filter)
            .group_by(Product.id, Product.name, Product.category)
        )
        rows = (await self.db.execute(stmt)).all()
        if not rows:
            return ReportProductPerformance()

        category_totals: dict[str | None, int] = {}
        for _id, _name, category, _units, revenue_cents in rows:
            category_totals[category] = category_totals.get(category, 0) + int(revenue_cents or 0)

        def _to_row(r) -> ReportProductRow:
            product_id, name, category, units, revenue_cents = r
            cat_total = category_totals.get(category, 0)
            share = round(100.0 * int(revenue_cents or 0) / cat_total, 1) if cat_total > 0 else None
            return ReportProductRow(
                product_id=product_id, product_name=name, category=category,
                units_sold=int(units or 0), revenue_cents=int(revenue_cents or 0),
                category_revenue_share_pct=share,
            )

        ranked_by_revenue = sorted(rows, key=lambda r: r[4] or 0, reverse=True)
        sold_only = [r for r in rows if (r[3] or 0) > 0]
        ranked_lowest = sorted(sold_only, key=lambda r: r[3] or 0)

        return ReportProductPerformance(
            top_products=[_to_row(r) for r in ranked_by_revenue[:5]],
            lowest_selling_products=[_to_row(r) for r in ranked_lowest[:5]],
        )
