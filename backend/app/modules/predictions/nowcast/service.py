"""Business logic for GET /events/{event_id}/revenue-forecast.

Fetches the event (with an explicit not-found vs. wrong-tenant
distinction — see the two exceptions below), sums confirmed revenue
transactions up to as_of_time, derives hour_offset_from_start from the
event's own first transaction, and calls the NowcastPredictor
singleton to produce the forecast.

"Confirmed" revenue = the same (source in slesh_pos, manual_bartender)
convention already used by the heuristic predictor's revenue rollup
(see predictions/predictors/heuristic.py's REVENUE_SOURCES comment:
"matches the Reports aggregator") — manual_adjustment and
reconciliation_correction rows are corrections, not sales, and parent
transactions only (price_cents is null on child/ingredient rows).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event
from app.modules.predictions.nowcast.predictor import get_predictor
from app.modules.predictions.nowcast.schemas import (
    HistoricalRange,
    PredictedCurvePoint,
    RevenueForecastResponse,
    confidence_tier,
)
from app.modules.stock_transactions.models import StockTransaction, TransactionSource

REVENUE_SOURCES = (TransactionSource.SLESH_POS, TransactionSource.MANUAL_BARTENDER)


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


async def _revenue_and_first_tx(
    db: AsyncSession, tenant_id: UUID, event_id: UUID, as_of_time: datetime,
) -> tuple[Decimal, datetime | None]:
    """Sum confirmed revenue (EUR) and find the earliest transaction
    time, both bounded to created_at <= as_of_time.

    Bounding first_tx_time by as_of_time (rather than taking the
    event's true first transaction unconditionally) is deliberate: if
    as_of_time is before the event's real start, this correctly
    returns None (no transactions yet -> hour_offset=0 upstream);
    once as_of_time is past the true start it converges to the same
    value either way, since MIN() over a growing window never changes
    once the earliest row is included.
    """
    stmt = (
        select(
            func.coalesce(func.sum(StockTransaction.price_cents), 0).label("revenue_cents"),
            func.min(StockTransaction.created_at).label("first_tx_time"),
        )
        .where(StockTransaction.tenant_id == tenant_id)
        .where(StockTransaction.event_id == event_id)
        .where(StockTransaction.price_cents.is_not(None))
        .where(StockTransaction.source.in_(REVENUE_SOURCES))
        .where(StockTransaction.created_at <= as_of_time)
    )
    row = (await db.execute(stmt)).one()
    revenue_eur = Decimal(row.revenue_cents) / Decimal(100)
    return revenue_eur, row.first_tx_time


async def get_revenue_forecast(
    db: AsyncSession,
    tenant_id: UUID,
    event_id: UUID,
    as_of_time: datetime,
) -> RevenueForecastResponse:
    event = await _get_event_or_raise(db, tenant_id, event_id)

    current_revenue, first_tx_time = await _revenue_and_first_tx(
        db, tenant_id, event_id, as_of_time,
    )

    if first_tx_time is None:
        hour_offset = 0.0
    else:
        hour_offset = (as_of_time - first_tx_time).total_seconds() / 3600.0
        hour_offset = max(hour_offset, 0.0)

    predictor = get_predictor()
    result = predictor.predict(
        float(current_revenue), hour_offset, target_year=event.scheduled_at.year,
    )

    curve = [
        PredictedCurvePoint(hour_offset=hr, cumulative_revenue_eur=val)
        for hr, val in sorted(result["predicted_curve"].items())
    ]

    return RevenueForecastResponse(
        event_id=event_id,
        as_of_time=as_of_time,
        hour_offset_from_start=round(hour_offset, 4),
        current_revenue_eur=float(current_revenue),
        predicted_final_revenue_eur=result["predicted_final_revenue_eur"],
        predicted_curve=curve,
        confidence=result["confidence"],
        vs_historical_avg_eur=result["vs_historical_avg_eur"],
        historical_range_eur=HistoricalRange(
            min=result["historical_range_eur"][0],
            max=result["historical_range_eur"][1],
        ),
        historical_n=result["historical_n"],
        confidence_tier=confidence_tier(result["confidence"]),
        training_events_count=result["training_events_count"],
        training_last_updated_at=result["training_last_updated_at"],
        year_weighted_prior_used=result["year_weighted_prior_used"],
    )
