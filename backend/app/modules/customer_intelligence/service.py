"""Business logic for GET /events/{event_id}/customer-intelligence.

Live stats for the CURRENT event are computed directly from
event_orders + stock_transactions/products, NOT from customer_sessions/
customer_purchases — those tables are built by an offline batch script
(build_customer_features.py) run after the fact, so they are empty/
stale for an event that is still LIVE. customer_sessions IS used, but
only for two things that are legitimately historical: deriving the
spend-segment thresholds (see constants.py) and looking up returning
guests from the 3 PRIOR identity events.

Reuses build_customer_features.py's bucket_category()/is_deposit_product()
directly rather than re-deriving the classification — those are the
tested, documented rules for this exact join.

Degrades independently per section: if the demand model has never been
trained (no active model_artifacts row), demand_forecast.available is
False and predicted_vs_actual is empty, but guests/spend_segments/
returning_guests still populate from live data. Nothing here raises for
a missing forecast — only for a genuinely missing/wrong-tenant event.
"""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customer_intelligence.constants import (
    IDENTITY_EVENT_IDS,
    LIGHT_SPEND_MAX_CENTS,
    WHALE_SPEND_MIN_CENTS,
)
from app.modules.customer_intelligence.schemas import (
    CategoryForecastOut,
    ConfidenceIntervalOut,
    CustomerIntelligenceResponse,
    DemandForecastOut,
    GuestCountsOut,
    HourlyPredictedVsActualOut,
    NextHourForecastOut,
    ReturningGuestsOut,
    SpendSegmentsOut,
)
from app.modules.events.models import Event
from app.modules.predictions.demand.loader import get_active_demand_predictor
from app.modules.predictions.demand.predictor import HOUR_GRID, DemandPredictor
from app.modules.predictions.demand.training_data import DRINK_CATEGORIES
from app.scripts.build_customer_features import bucket_category, is_deposit_product

LOW_CONFIDENCE_CATEGORIES = frozenset({"cocktail", "spritz"})
CACHE_TTL_SECONDS = 30
logger = logging.getLogger(__name__)


class EventNotFoundError(Exception):
    """event_id does not exist in ANY tenant. Maps to 404."""


class EventNotInTenantError(Exception):
    """event_id exists, but belongs to a different tenant. Maps to 403."""


async def _get_event_or_raise(db: AsyncSession, tenant_id: UUID, event_id: UUID) -> Event:
    event = await db.get(Event, event_id)
    if event is None:
        raise EventNotFoundError(f"Event {event_id} not found")
    if event.tenant_id != tenant_id:
        raise EventNotInTenantError(f"Event {event_id} does not belong to this tenant")
    return event


_CUSTOMER_ORDER_ROWS_SQL = text("""
    select
        raw_extras->'user'->>'_id'  as customer_key,
        coalesce(fiscal_gross_cents, 0) as spend_cents,
        customer_email
    from event_orders
    where event_id = :event_id and tenant_id = :tenant_id
      and created_at_slesh <= :as_of_time
      and raw_extras->'user'->>'_id' is not null
""")

_PURCHASE_LINE_ROWS_SQL = text("""
    select
        eo.created_at_slesh as ordered_at,
        p.name as product_name,
        p.product_type as product_type,
        p.category as product_category
    from stock_transactions st
    join event_orders eo
      on eo.slesh_order_id = split_part(st.source_idempotency_key, ':', 2)
     and eo.event_id = st.event_id
    join products p on p.id = st.product_id
    where st.event_id = :event_id and st.tenant_id = :tenant_id
      and st.source_idempotency_key like 'slesh:%'
      and eo.created_at_slesh <= :as_of_time
""")

_RETURNING_CUSTOMER_KEYS_SQL = text("""
    select distinct customer_key from customer_sessions
    where event_id = any(:other_event_ids)
""")


def _is_registered(customer_email: str | None) -> bool | None:
    """Mirrors CustomerSession.is_registered semantics: True if the
    customer's email domain isn't slesh.it, False if it is, None
    (unknown) if there's no email at all."""
    if not customer_email or "@" not in customer_email:
        return None
    domain = customer_email.rsplit("@", 1)[-1].lower()
    return domain != "slesh.it"


async def _live_guest_stats(
    db: AsyncSession, tenant_id: UUID, event_id: UUID, as_of_time: datetime,
) -> tuple[dict[str, int], set[str]]:
    """Aggregates event_orders (live-updated by order_ingester) into one
    row per identified customer. Returns (segment_counts, customer_keys) —
    the caller cross-references customer_keys against prior events for
    returning-guest recognition."""
    rows = (await db.execute(_CUSTOMER_ORDER_ROWS_SQL, {
        "event_id": event_id, "tenant_id": tenant_id, "as_of_time": as_of_time,
    })).mappings().all()

    per_customer: dict[str, dict] = {}
    for r in rows:
        key = r["customer_key"]
        c = per_customer.setdefault(key, {"spend_cents": 0, "registered": None})
        c["spend_cents"] += r["spend_cents"]
        reg = _is_registered(r["customer_email"])
        # True/False from any order wins over "unknown" (None) — a
        # customer only needs one order with an email to be classified.
        if reg is not None:
            c["registered"] = reg

    registered = sum(1 for c in per_customer.values() if c["registered"] is True)
    guest = sum(1 for c in per_customer.values() if c["registered"] is False)
    unknown = sum(1 for c in per_customer.values() if c["registered"] is None)
    whale = sum(1 for c in per_customer.values() if c["spend_cents"] >= WHALE_SPEND_MIN_CENTS)
    light = sum(1 for c in per_customer.values() if c["spend_cents"] <= LIGHT_SPEND_MAX_CENTS)
    regular = len(per_customer) - whale - light

    counts = {
        "live_identified_count": len(per_customer),
        "registered_count": registered,
        "guest_count": guest,
        "unknown_count": unknown,
        "whale_count": whale,
        "regular_count": regular,
        "light_count": light,
    }
    return counts, set(per_customer.keys())


async def _live_drinks_grid(
    db: AsyncSession, tenant_id: UUID, event_id: UUID, as_of_time: datetime,
) -> tuple[datetime | None, dict[int, dict[str, float]]]:
    """Returns (first_order_at, {hour_of_event: {category: count}}) for
    real drink lines only (deposit/food excluded), computed live from
    the same stock_transactions<->event_orders join
    build_customer_features.py uses — see that script's docstring rules
    3-8 for why this exact join and this exact ordered_at source."""
    rows = (await db.execute(_PURCHASE_LINE_ROWS_SQL, {
        "event_id": event_id, "tenant_id": tenant_id, "as_of_time": as_of_time,
    })).mappings().all()
    if not rows:
        return None, {}

    first_order_at = min(r["ordered_at"] for r in rows)
    grid: dict[int, dict[str, float]] = {}
    for r in rows:
        if is_deposit_product(r["product_name"]):
            continue
        category = bucket_category(r["product_type"], r["product_category"], r["product_name"])
        if category not in DRINK_CATEGORIES:
            continue  # food / unmapped
        hour = int((r["ordered_at"] - first_order_at).total_seconds() // 3600)
        grid.setdefault(hour, {})
        grid[hour][category] = grid[hour].get(category, 0.0) + 1.0
    return first_order_at, grid


def _hour_total(grid: dict[int, dict[str, float]], hour: int) -> float:
    return sum(grid.get(hour, {}).values())


def _cumulative_through(grid: dict[int, dict[str, float]], hour: int) -> float:
    return sum(_hour_total(grid, h) for h in grid if h <= hour)


def _predicted_by_hour_total(prediction: dict, hour: float) -> float:
    by_bar = prediction["predicted_by_hour"].get(round(float(hour), 1), {})
    return sum(by_cat.get(cat, 0.0) for by_cat in by_bar.values() for cat in DRINK_CATEGORIES)


def _predicted_by_hour_categories(prediction: dict, hour: float) -> dict[str, float]:
    by_bar = prediction["predicted_by_hour"].get(round(float(hour), 1), {})
    totals: dict[str, float] = {cat: 0.0 for cat in DRINK_CATEGORIES}
    for by_cat in by_bar.values():
        for cat, val in by_cat.items():
            totals[cat] = totals.get(cat, 0.0) + val
    return totals


def _build_demand_forecast(
    predictor: DemandPredictor | None, drinks_so_far: float, hour_offset: float, hot_night: bool,
    unavailable_reason: str | None = None,
) -> DemandForecastOut:
    if predictor is None:
        # unavailable_reason distinguishes "never trained" from "was
        # trained, artifact unavailable" — see loader.py. Falls back to
        # the former only if a caller somehow didn't pass one through.
        return DemandForecastOut(
            available=False, unavailable_reason=unavailable_reason or "demand model not yet trained",
        )

    prediction = predictor.predict(drinks_so_far, hour_offset, hot_night=hot_night)
    ci = ConfidenceIntervalOut(**prediction["confidence_interval"])

    next_hour = next((h for h in HOUR_GRID if h > hour_offset), None)
    next_hour_out = None
    if next_hour is not None:
        next_hour_cats = _predicted_by_hour_categories(prediction, next_hour)
        next_hour_total = sum(next_hour_cats.values())
        # The whole-event confidence_interval's half-width is the only
        # fitted uncertainty this model has (see fit_interval_table) —
        # applied proportionally to this hour's slice of the predicted
        # total, since there is no separately-fitted per-hour band.
        half_width = ci.half_width_pct / 100.0
        next_hour_out = NextHourForecastOut(
            predicted_total=round(next_hour_total, 1),
            confidence_interval=ConfidenceIntervalOut(
                lower=round(max(0.0, next_hour_total * (1 - half_width)), 1),
                upper=round(next_hour_total * (1 + half_width), 1),
                half_width_pct=ci.half_width_pct,
                calibrated=ci.calibrated,
            ),
            category_breakdown=[
                CategoryForecastOut(
                    category=cat, predicted_count=round(val, 1),
                    low_confidence=cat in LOW_CONFIDENCE_CATEGORIES,
                )
                for cat, val in sorted(next_hour_cats.items())
            ],
        )

    return DemandForecastOut(
        available=True,
        predicted_final_total=prediction["predicted_final_total"],
        confidence=prediction["confidence"],
        confidence_interval=ci,
        next_hour=next_hour_out,
        hot_night_applied=prediction["hot_night_applied"],
    )


def _build_predicted_vs_actual(
    predictor: DemandPredictor | None, grid: dict[int, dict[str, float]], hour_offset: float, hot_night: bool,
) -> list[HourlyPredictedVsActualOut]:
    """For every fully-closed hour (target <= floor(hour_offset)),
    predicts it using ONLY the actuals known before that hour started —
    the same "actuals-through-h -> predict h+1" checkpoint protocol
    validate_demand_model.py uses — then compares against what actually
    happened. Updates naturally as as_of_time advances and more hours
    close; nothing is persisted."""
    if predictor is None:
        return []
    out = []
    for target in HOUR_GRID:
        if target <= 0 or target > hour_offset:
            continue
        h_now = target - 1.0
        observed_so_far = _cumulative_through(grid, int(h_now))
        prediction = predictor.predict(observed_so_far, h_now, hot_night=hot_night)
        predicted = _predicted_by_hour_total(prediction, target)
        actual = _hour_total(grid, int(target))
        out.append(HourlyPredictedVsActualOut(
            hour_of_event=target, predicted=round(predicted, 1), actual=actual,
        ))
    return out


async def set_hot_night_override(
    db: AsyncSession, tenant_id: UUID, event_id: UUID, enabled: bool,
) -> Event:
    """Flip the manual heat-adjustment toggle (see predictor.py's
    apply_hot_night_boost). Deliberately NOT routed through
    EventService's optimistic-locking update — this is a narrow,
    idempotent operational toggle a manager flips mid-event, not a
    structural edit, and shouldn't 409 on an unrelated concurrent
    version bump."""
    event = await _get_event_or_raise(db, tenant_id, event_id)
    event.hot_night_override = enabled
    await db.commit()
    await db.refresh(event)
    return event


async def get_customer_intelligence(
    db: AsyncSession, tenant_id: UUID, event_id: UUID, as_of_time: datetime,
) -> CustomerIntelligenceResponse:
    event = await _get_event_or_raise(db, tenant_id, event_id)

    segment_counts, customer_keys = await _live_guest_stats(db, tenant_id, event_id, as_of_time)

    other_identity_ids = list(IDENTITY_EVENT_IDS - {event_id})
    returning_count = 0
    if customer_keys and other_identity_ids:
        prior_keys = set((await db.execute(_RETURNING_CUSTOMER_KEYS_SQL, {
            "other_event_ids": other_identity_ids,
        })).scalars().all())
        returning_count = len(customer_keys & prior_keys)

    first_order_at, grid = await _live_drinks_grid(db, tenant_id, event_id, as_of_time)
    if first_order_at is None:
        hour_offset = None
        drinks_so_far = 0.0
    else:
        hour_offset = max(0.0, (as_of_time - first_order_at).total_seconds() / 3600.0)
        drinks_so_far = sum(_hour_total(grid, h) for h in grid)

    predictor, load_reason = await get_active_demand_predictor(db, tenant_id)

    live_count = segment_counts["live_identified_count"]
    projected_final: float | None = live_count or None
    if predictor is not None and hour_offset is not None and live_count > 0:
        f_now = predictor.shape_fraction_at(hour_offset)
        if f_now >= 1e-3:
            projected_final = round(live_count / f_now, 1)

    demand_forecast = _build_demand_forecast(
        predictor, drinks_so_far, hour_offset if hour_offset is not None else 0.0,
        event.hot_night_override, load_reason,
    ) if hour_offset is not None else DemandForecastOut(
        available=False, unavailable_reason="no orders yet — doors have not opened",
    )

    predicted_vs_actual = (
        _build_predicted_vs_actual(predictor, grid, hour_offset, event.hot_night_override)
        if hour_offset is not None else []
    )

    return CustomerIntelligenceResponse(
        event_id=event_id,
        as_of_time=as_of_time,
        hour_offset_from_start=round(hour_offset, 4) if hour_offset is not None else None,
        guests=GuestCountsOut(
            live_identified_count=live_count,
            projected_final=projected_final,
            registered_count=segment_counts["registered_count"],
            guest_count=segment_counts["guest_count"],
            unknown_count=segment_counts["unknown_count"],
        ),
        spend_segments=SpendSegmentsOut(
            whale_count=segment_counts["whale_count"],
            regular_count=segment_counts["regular_count"],
            light_count=segment_counts["light_count"],
            whale_threshold_cents=WHALE_SPEND_MIN_CENTS,
            light_threshold_cents=LIGHT_SPEND_MAX_CENTS,
        ),
        returning_guests=ReturningGuestsOut(
            returning_count=returning_count,
            new_count=live_count - returning_count,
            identified_total=live_count,
        ),
        demand_forecast=demand_forecast,
        predicted_vs_actual=predicted_vs_actual,
        hot_night_override=event.hot_night_override,
    )


def _cache_key(tenant_id: UUID, event_id: UUID) -> str:
    return f"customer_intel:{tenant_id}:{event_id}"


async def get_customer_intelligence_cached(
    db: AsyncSession, tenant_id: UUID, event_id: UUID, as_of_time: datetime, *, use_cache: bool,
) -> CustomerIntelligenceResponse:
    """Wraps get_customer_intelligence with a ~30s Redis cache — this
    endpoint is polled during a live event (Day 4 spec) and does two
    non-trivial live queries + a model prediction per call. use_cache
    should be False for any caller passing an explicit historical
    as_of_time (a backtest/preview, not "what's happening right now"),
    matching the revenue-forecast endpoint's as_of_time semantics.

    Cache failure (Redis down) degrades to computing fresh — caching is
    an optimization, never a hard dependency for this endpoint to work.
    """
    if not use_cache:
        return await get_customer_intelligence(db, tenant_id, event_id, as_of_time)

    try:
        from app.core.redis_client import get_redis
        r = await get_redis()
        cached = await r.get(_cache_key(tenant_id, event_id))
        if cached is not None:
            return CustomerIntelligenceResponse.model_validate_json(cached)
    except Exception as exc:  # noqa: BLE001
        logger.warning("customer_intelligence cache read failed: %s", exc)

    result = await get_customer_intelligence(db, tenant_id, event_id, as_of_time)

    try:
        r = await get_redis()
        await r.set(_cache_key(tenant_id, event_id), result.model_dump_json(), ex=CACHE_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.warning("customer_intelligence cache write failed: %s", exc)

    return result
