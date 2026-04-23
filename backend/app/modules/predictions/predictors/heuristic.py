"""Heuristic prediction engine — historical averages with per-guest scaling.

The v1.0 predictor. Deterministic math, no ML, no training. Takes completed
historical events, computes per-guest averages, scales them to the target
event's expected_guest_count, and derives the 5 predictions required by
spec §3.2.

Design principles:
  - Honest over impressive: wide confidence ranges when history is small,
    narrow when it's large.
  - Deterministic: the same inputs always produce the same outputs. No
    randomness, no ML weights, no temperature.
  - Self-improving: every new completed event adds to the sample. The
    heuristic doesn't "retrain" — it just computes over a larger pool.

Performance: one DB query (historical events) + light Python math.
Target latency < 2s per spec §11.

Spec: docs/predictions-module-spec.md §5.1.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.modules.bars.models import Bar
from app.modules.events.models import Event, EventStatus
from app.modules.predictions.predictors.base import (
    BasePredictor,
    PredictorResult,
)
from app.modules.predictions.repository import PredictionRepository
from app.modules.predictions.schemas import (
    PredictionBarRevenue,
    PredictionBarStaff,
    PredictionCategoryDemand,
    PredictionData,
    PredictionInsufficientData,
    PredictionPeakHour,
    PredictionRange,
    PredictionRevenue,
    PredictionRiskFlag,
    PredictionStaff,
)
from app.modules.reports.schemas import ReportEventInfo
from app.modules.stock_transactions.models import StockTransaction

# Revenue-counting transaction sources (matches the Reports aggregator).
REVENUE_SOURCES = ("slesh_pos", "manual_bartender")

# Category mapping heuristic — maps product names to the 5 UI categories.
# Rough keyword matching; future versions will use a proper product_category
# column. Kept explicit here so it's easy to audit.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "beer": ("beer", "lager", "ale", "pilsner", "stout", "birra"),
    "spirits": ("vodka", "gin", "rum", "whisky", "whiskey", "tequila", "bourbon"),
    "wine": ("wine", "vino", "prosecco", "champagne", "spumante"),
    "mixers": ("tonic", "soda", "cola", "juice", "lime", "lemon"),
    "cocktails": ("cocktail", "mojito", "spritz", "negroni", "martini", "margarita"),
}


def _classify_category(product_name: str) -> str:
    """Best-effort classification from product name."""
    name = product_name.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in name for kw in keywords):
            return category
    return "cocktails"  # sensible default for unrecognized products


def _mean_std(values: Sequence[float]) -> tuple[float, float]:
    """Sample mean + std-dev. Guards against small-n edge cases."""
    if not values:
        return 0.0, 0.0
    mean = statistics.fmean(values)
    if len(values) < 2:
        # Single sample — use ±50% as a wide default band.
        return mean, mean * 0.5
    return mean, statistics.stdev(values)


def _range_from(mean: float, stddev: float, n: int) -> PredictionRange:
    """Build a PredictionRange from sample stats.

    Uses a simple Normal approximation: range = mean ± 1.28σ (~80% CI).
    For tiny samples we widen further. Quant wisdom says don't bother with
    t-distributions at n<30 when the inputs are already noisy; just be honest
    with the confidence number.
    """
    if n < 2:
        confidence = 50.0  # one data point is a guess, not a forecast
        half_width = max(mean * 0.5, 1.0)
    elif n < 5:
        confidence = 65.0
        half_width = stddev * 1.5
    elif n < 15:
        confidence = 75.0
        half_width = stddev * 1.28
    else:
        confidence = 85.0
        half_width = stddev * 1.28

    low = max(0.0, mean - half_width)
    high = mean + half_width
    return PredictionRange(
        low=Decimal(str(round(low, 2))),
        mid=Decimal(str(round(mean, 2))),
        high=Decimal(str(round(high, 2))),
        confidence_pct=confidence,
    )


def _confidence_tier(n: int) -> str:
    """Event-count → tier label shown in the UI."""
    if n >= 15:
        return "high"
    if n >= 5:
        return "medium"
    return "low"


class HeuristicPredictor(BasePredictor):
    """v1.0 predictor — scales historical per-guest averages."""

    @property
    def predictor_type(self) -> str:
        return "heuristic"

    def minimum_events_required(self) -> int:
        # One completed event is the minimum to have any basis at all.
        # Below that we emit PredictionInsufficientData.
        return 1

    async def is_ready(self, tenant_id: UUID) -> bool:
        """Readiness check for service-layer routing.

        Returns True if the tenant has at least one usable historical event.
        'Usable' means: completed, with ended_at set, AND had revenue-
        producing transactions (zero-revenue smoke-test events don't count).
        """
        stmt = (
            select(func.count(func.distinct(Event.id)))
            .join(StockTransaction, StockTransaction.event_id == Event.id)
            .where(
                Event.tenant_id == tenant_id,
                Event.status == EventStatus.COMPLETED,
                Event.ended_at.is_not(None),
                StockTransaction.source.in_(REVENUE_SOURCES),
                StockTransaction.price_cents.is_not(None),
            )
        )
        count = (await self.db.execute(stmt)).scalar_one() or 0
        return count >= self.minimum_events_required()

    # ─── Public: predict ──────────────────────────────────────────────────

    async def predict(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> PredictorResult:
        """Produce a PredictionData or PredictionInsufficientData for event_id."""

        # Load target event
        target_event = await self._load_target_event(tenant_id, event_id)
        if target_event is None:
            return PredictionInsufficientData(
                reason="event_not_found",
                user_message="Event not found for this tenant.",
                events_available=0,
                events_required=self.minimum_events_required(),
            )

        if target_event.expected_guest_count is None or target_event.expected_guest_count <= 0:
            return PredictionInsufficientData(
                reason="missing_expected_guest_count",
                user_message=(
                    "Set an expected guest count on the event before generating "
                    "predictions. The forecast scales historical averages to your "
                    "expected crowd size."
                ),
                events_available=0,
                events_required=self.minimum_events_required(),
            )

        # Load training history (excluding self)
        repo = PredictionRepository(self.db)
        historical_events = await repo.list_historical_completed_events(
            tenant_id=tenant_id,
            exclude_event_id=event_id,
            limit=50,
        )

        # Filter down to events that actually had revenue-producing transactions.
        usable = await self._filter_events_with_revenue(historical_events)

        if len(usable) < self.minimum_events_required():
            return PredictionInsufficientData(
                reason="insufficient_history",
                user_message=(
                    "Predictions will appear after your first completed event. "
                    "The system learns from every event you run — revenue "
                    "patterns, peak hours, stock consumption."
                ),
                events_available=len(usable),
                events_required=self.minimum_events_required(),
            )

        # Aggregate per-guest stats across historical events
        stats = await self._compute_historical_stats(usable)

        # Build each of the 5 predictions
        revenue = self._predict_revenue(
            target_event, stats, historical_n=len(usable)
        )
        category_demand = self._predict_category_demand(
            target_event, stats, historical_n=len(usable)
        )
        peak_hour = self._predict_peak_hour(target_event, stats)
        staff = await self._predict_staff(
            tenant_id, event_id, target_event, stats, historical_n=len(usable)
        )
        risk_flags = await self._predict_risk_flags(
            tenant_id, event_id, target_event, stats
        )

        # Build event info (reuse Reports schema)
        duration_hours = 0.0
        if target_event.started_at and target_event.ended_at:
            duration_hours = round(
                (target_event.ended_at - target_event.started_at).total_seconds() / 3600,
                2,
            )
        event_info = ReportEventInfo(
            event_id=target_event.id,
            event_name=target_event.name,
            venue_name=stats.get("_target_venue_name", "—"),
            started_at=target_event.started_at or datetime.now(timezone.utc),
            ended_at=target_event.ended_at or datetime.now(timezone.utc),
            duration_hours=duration_hours,
            bars_count=stats.get("_target_bars_count", 0),
            guests_served=None,
            expected_guest_count=target_event.expected_guest_count,
        )

        return PredictionData(
            prediction_id=uuid4(),
            version=0,  # service layer overrides with real version
            generated_at=datetime.now(timezone.utc),
            based_on_event_count=len(usable),
            confidence_tier=_confidence_tier(len(usable)),
            event=event_info,
            revenue=revenue,
            category_demand=category_demand,
            peak_hour=peak_hour,
            staff=staff,
            risk_flags=risk_flags,
        )

    # ─── Private helpers ──────────────────────────────────────────────────

    async def _load_target_event(
        self, tenant_id: UUID, event_id: UUID
    ) -> Event | None:
        stmt = select(Event).where(
            Event.tenant_id == tenant_id,
            Event.id == event_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _filter_events_with_revenue(
        self, events: Sequence[Event]
    ) -> list[Event]:
        """Keep only events that had actual revenue — excludes smoke-test events."""
        if not events:
            return []
        event_ids = [e.id for e in events]
        stmt = (
            select(StockTransaction.event_id)
            .where(
                StockTransaction.event_id.in_(event_ids),
                StockTransaction.source.in_(REVENUE_SOURCES),
                StockTransaction.price_cents.is_not(None),
            )
            .group_by(StockTransaction.event_id)
            .having(func.sum(StockTransaction.qty * StockTransaction.price_cents) > 0)
        )
        rows = (await self.db.execute(stmt)).all()
        ids_with_revenue = {r[0] for r in rows}
        return [e for e in events if e.id in ids_with_revenue]

    async def _compute_historical_stats(
        self, events: Sequence[Event]
    ) -> dict:
        """Build a stats dict of per-guest metrics across all training events.

        Keys include:
          revenues_per_guest      : list[float]
          total_revenues          : list[float]
          guest_counts            : list[int]
          category_per_guest      : dict[str, list[float]]
          peak_hour_offsets       : list[float]  (hours from event start)
          bars_counts             : list[int]
        """
        stats: dict = {
            "revenues_per_guest": [],
            "total_revenues": [],
            "guest_counts": [],
            "category_per_guest": {cat: [] for cat in CATEGORY_KEYWORDS.keys()},
            "peak_hour_offsets": [],
            "bars_counts": [],
        }

        for event in events:
            if event.expected_guest_count is None or event.expected_guest_count <= 0:
                continue

            # Per-event revenue
            rev_stmt = (
                select(
                    func.coalesce(
                        func.sum(
                            StockTransaction.qty * StockTransaction.price_cents
                        ),
                        0,
                    )
                )
                .where(
                    StockTransaction.event_id == event.id,
                    StockTransaction.source.in_(REVENUE_SOURCES),
                    StockTransaction.price_cents.is_not(None),
                )
            )
            total_cents = (await self.db.execute(rev_stmt)).scalar_one() or 0
            total_revenue = float(total_cents) / 100.0

            guests = event.expected_guest_count
            stats["total_revenues"].append(total_revenue)
            stats["guest_counts"].append(guests)
            stats["revenues_per_guest"].append(total_revenue / guests)

            # Per-category units-per-guest
            cat_stmt = (
                select(
                    StockTransaction.product_id,
                    func.sum(StockTransaction.qty),
                )
                .where(
                    StockTransaction.event_id == event.id,
                    StockTransaction.source.in_(REVENUE_SOURCES),
                )
                .group_by(StockTransaction.product_id)
            )
            cat_rows = (await self.db.execute(cat_stmt)).all()

            # Resolve product names in one query
            from app.modules.products.models import Product
            product_ids = [r[0] for r in cat_rows]
            if product_ids:
                name_stmt = select(Product.id, Product.name).where(
                    Product.id.in_(product_ids)
                )
                name_rows = (await self.db.execute(name_stmt)).all()
                id_to_name = {r[0]: r[1] for r in name_rows}

                per_cat: dict[str, float] = {cat: 0.0 for cat in CATEGORY_KEYWORDS}
                for prod_id, qty in cat_rows:
                    name = id_to_name.get(prod_id, "")
                    category = _classify_category(name)
                    per_cat[category] += float(qty or 0)

                for cat, units in per_cat.items():
                    stats["category_per_guest"][cat].append(units / guests)

            # Peak hour offset (hour of day with max revenue, relative to event start)
            if event.started_at:
                peak_stmt = (
                    select(
                        func.date_trunc("hour", StockTransaction.created_at).label("hr"),
                        func.sum(
                            StockTransaction.qty * StockTransaction.price_cents
                        ).label("rev"),
                    )
                    .where(
                        StockTransaction.event_id == event.id,
                        StockTransaction.source.in_(REVENUE_SOURCES),
                    )
                    .group_by("hr")
                    .order_by(func.sum(
                        StockTransaction.qty * StockTransaction.price_cents
                    ).desc())
                    .limit(1)
                )
                peak_row = (await self.db.execute(peak_stmt)).first()
                if peak_row and peak_row[0]:
                    offset_h = (peak_row[0] - event.started_at).total_seconds() / 3600
                    stats["peak_hour_offsets"].append(offset_h)

            # Bars count
            bars_stmt = select(func.count(Bar.id)).where(
                Bar.tenant_id == event.tenant_id,
                Bar.event_id == event.id,
                Bar.is_active.is_(True),
            )
            bars_count = (await self.db.execute(bars_stmt)).scalar_one() or 0
            stats["bars_counts"].append(int(bars_count))

        return stats

    # ─── Prediction slices ────────────────────────────────────────────────

    def _predict_revenue(
        self, target: Event, stats: dict, historical_n: int
    ) -> PredictionRevenue:
        rpg_values = stats["revenues_per_guest"]
        mean_rpg, std_rpg = _mean_std(rpg_values)
        guests = target.expected_guest_count or 0

        predicted_mean = mean_rpg * guests
        predicted_std = std_rpg * guests
        total_range = _range_from(predicted_mean, predicted_std, historical_n)

        # vs last event pct
        vs_last = None
        if stats["total_revenues"]:
            last = stats["total_revenues"][0]  # events ordered DESC by ended_at
            if last > 0:
                vs_last = round((predicted_mean - last) / last * 100, 1)

        return PredictionRevenue(
            total=total_range,
            per_bar=[],  # left empty in v1.0 — bar_revenues require more detail
            vs_last_event_pct=vs_last,
        )

    def _predict_category_demand(
        self, target: Event, stats: dict, historical_n: int
    ) -> list[PredictionCategoryDemand]:
        guests = target.expected_guest_count or 0
        out: list[PredictionCategoryDemand] = []

        for category, upg_values in stats["category_per_guest"].items():
            if not upg_values:
                continue  # skip categories we've never sold
            mean_upg, std_upg = _mean_std(upg_values)
            units_mean = mean_upg * guests
            units_std = std_upg * guests
            units_range = _range_from(units_mean, units_std, historical_n)

            # Trend: last event vs average
            recent = upg_values[0] if upg_values else mean_upg
            if recent > mean_upg * 1.1:
                trend = "up"
            elif recent < mean_upg * 0.9:
                trend = "down"
            else:
                trend = "stable"

            out.append(PredictionCategoryDemand(
                category=category,  # type: ignore[arg-type]
                units=units_range,
                trend=trend,  # type: ignore[arg-type]
            ))

        return out

    def _predict_peak_hour(
        self, target: Event, stats: dict
    ) -> PredictionPeakHour | None:
        offsets = stats["peak_hour_offsets"]
        if not offsets or not target.started_at:
            return None

        mean_offset = statistics.fmean(offsets)
        window_start = target.started_at + timedelta(hours=mean_offset)
        window_end = window_start + timedelta(hours=1)

        # Share is typically 25-40% of event revenue concentrated in peak hour
        # when events have a single peak. Ballpark 32% for now; Track 2 will
        # compute this from historical share distributions.
        share_pct = 32.0

        return PredictionPeakHour(
            window_start=window_start,
            window_end=window_end,
            predicted_revenue_share_pct=share_pct,
        )

    async def _predict_staff(
        self,
        tenant_id: UUID,
        event_id: UUID,
        target: Event,
        stats: dict,
        historical_n: int,
    ) -> PredictionStaff:
        """Staff recommendation: ~1 bartender per 50 guests per bar.

        Simple rule of thumb from hospitality industry norms. Track 2 will
        learn the real ratio from event_outcomes.staff_count if provided.
        """
        guests = target.expected_guest_count or 0

        # Count bars configured for this event
        bars_stmt = select(func.count(Bar.id)).where(
            Bar.tenant_id == tenant_id,
            Bar.event_id == event_id,
            Bar.is_active.is_(True),
        )
        bars_count = (await self.db.execute(bars_stmt)).scalar_one() or 0

        # Rule of thumb: 1 bartender per 50 guests, minimum 1 per bar
        if bars_count > 0:
            total_bartenders_mean = max(bars_count, math.ceil(guests / 50))
        else:
            total_bartenders_mean = max(1, math.ceil(guests / 50))

        # Wide-ish band for staff (±20%)
        total_range = PredictionRange(
            low=Decimal(str(max(1, int(total_bartenders_mean * 0.8)))),
            mid=Decimal(str(total_bartenders_mean)),
            high=Decimal(str(int(total_bartenders_mean * 1.2) + 1)),
            confidence_pct=70.0 if historical_n >= 3 else 55.0,
        )

        return PredictionStaff(total_bartenders=total_range, per_bar=[])

    async def _predict_risk_flags(
        self,
        tenant_id: UUID,
        event_id: UUID,
        target: Event,
        stats: dict,
    ) -> list[PredictionRiskFlag]:
        """Risk flags — products likely to run out given forecast demand.

        v1.0 heuristic: for each (bar, product) in this event's bar_stock,
        estimate expected consumption from historical per-guest averages,
        compare to allocated_qty. If expected > 90% of allocated, flag.

        Returns [] gracefully if the event has no bar_stock configured yet.
        """
        from app.modules.bar_stock.models import BarStock
        from app.modules.products.models import Product

        stmt = (
            select(
                BarStock.bar_id,
                Bar.name.label("bar_name"),
                BarStock.product_id,
                Product.name.label("product_name"),
                BarStock.allocated_qty,
            )
            .join(Bar, Bar.id == BarStock.bar_id)
            .join(Product, Product.id == BarStock.product_id)
            .where(
                BarStock.tenant_id == tenant_id,
                BarStock.event_id == event_id,
            )
        )
        rows = (await self.db.execute(stmt)).all()
        if not rows:
            return []

        guests = target.expected_guest_count or 0
        flags: list[PredictionRiskFlag] = []

        # Aggregate per-category mean upg for lookup
        per_cat_means = {
            cat: (statistics.fmean(vals) if vals else 0.0)
            for cat, vals in stats["category_per_guest"].items()
        }

        for bar_id, bar_name, product_id, product_name, allocated in rows:
            alloc_f = float(allocated or 0)
            if alloc_f <= 0:
                continue
            category = _classify_category(product_name)
            upg = per_cat_means.get(category, 0.0)
            expected_consumption = upg * guests

            # Only flag if the product is in the top-consumed categories and
            # expected > 90% allocated. Below that threshold, no flag.
            if alloc_f > 0 and expected_consumption >= alloc_f * 0.9:
                probability = min(1.0, expected_consumption / alloc_f)
                # Predicted stockout time: roughly when cumulative consumption
                # matches allocated, assuming linear burn. Approximate mid-event.
                predicted_time = None
                if target.started_at and target.ended_at:
                    duration = target.ended_at - target.started_at
                    # Simple linear projection: time_to_depletion = alloc/expected * duration
                    frac = alloc_f / expected_consumption if expected_consumption > 0 else 1.0
                    predicted_time = target.started_at + (duration * min(frac, 1.0))

                flags.append(PredictionRiskFlag(
                    product_id=product_id,
                    product_name=product_name,
                    bar_id=bar_id,
                    bar_name=bar_name,
                    stockout_probability=round(probability, 2),
                    predicted_stockout_time=predicted_time,
                ))

        # Sort by probability DESC so the riskiest items are first
        flags.sort(key=lambda f: f.stockout_probability, reverse=True)
        return flags
