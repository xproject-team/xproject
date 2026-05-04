"""Weather sync service — fetch + persist Open-Meteo forecasts.

The single responsibility of this module is: given an event_id, fetch
the latest weather forecast for its venue and persist the snapshot on
the event row.

It NEVER mutates anything else. Callers (CLI, future cron) decide when
to fire this.

Spec: docs/slesh-integration-roadmap.md (Phase B - Weather Integration).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Side-effect import: Tenant must be registered in SQLAlchemy's metadata
# before we flush FK-bearing rows. Same pattern as poll_state_models.py.
from app.modules.auth.models    import Tenant  # noqa: F401
from app.modules.events.models  import Event
from app.modules.venues.models  import Venue
from app.modules.weather.adapter import WeatherAdapter

logger = logging.getLogger(__name__)


@dataclass
class WeatherSyncResult:
    """Outcome of a single sync call."""
    status:        str                   # ok | skipped | error
    event_id:      UUID
    reason:        str | None = None      # for skipped/error
    fetched_at:    datetime | None = None
    current_temp:  float | None = None    # quick-glance for logs

    def __str__(self) -> str:
        if self.status != "ok":
            return f"WeatherSyncResult(status={self.status} event={self.event_id} reason={self.reason!r})"
        return (
            f"WeatherSyncResult(status=ok event={self.event_id} "
            f"temp={self.current_temp}\u00b0C fetched_at={self.fetched_at})"
        )


async def fetch_and_store_for_event(
    *,
    db:        AsyncSession,
    event_id:  UUID,
    tenant_id: UUID,
    timezone_name: str = "Europe/Rome",
    forecast_days: int = 2,
) -> WeatherSyncResult:
    """Fetch weather for the venue of `event_id` and persist on the event row.

    Returns a WeatherSyncResult with status:
      - ok:      snapshot was written to events.weather_snapshot
      - skipped: venue has no coordinates (clear log line, no error)
      - error:   any failure path (network, parse, DB)

    Caller is responsible for committing the session. We flush only.
    """
    # 1. Load event + venue
    stmt = (
        select(Event, Venue)
        .join(Venue, Venue.id == Event.venue_id)
        .where(Event.id == event_id)
        .where(Event.tenant_id == tenant_id)
    )
    res = await db.execute(stmt)
    row = res.one_or_none()
    if row is None:
        return WeatherSyncResult(
            status="error",
            event_id=event_id,
            reason="event not found for tenant",
        )

    event, venue = row

    # 2. Defensive: venue must have lat/lon
    if venue.latitude is None or venue.longitude is None:
        logger.warning(
            "weather_sync: venue %s (%s) has no coordinates — skipping event %s",
            venue.id, venue.name, event_id,
        )
        return WeatherSyncResult(
            status="skipped",
            event_id=event_id,
            reason=f"venue {venue.name!r} has no latitude/longitude",
        )

    # 3. Fetch from Open-Meteo
    try:
        async with WeatherAdapter() as wx:
            forecast = await wx.fetch_forecast(
                latitude      = float(venue.latitude),
                longitude     = float(venue.longitude),
                timezone      = timezone_name,
                forecast_days = forecast_days,
            )
    except Exception as exc:                       # noqa: BLE001
        logger.exception("weather_sync: fetch failed for event %s", event_id)
        return WeatherSyncResult(
            status="error",
            event_id=event_id,
            reason=f"{type(exc).__name__}: {exc}",
        )

    # 4. Persist snapshot
    snapshot = forecast.model_dump(mode="json")    # full raw response as JSONB
    now      = datetime.now(tz=timezone.utc)
    event.weather_snapshot   = snapshot
    event.weather_fetched_at = now
    db.add(event)
    await db.flush()

    current_temp = forecast.current.temperature_2m if forecast.current else None
    logger.info(
        "weather_sync: event=%s venue=%s temp=%s\u00b0C",
        event_id, venue.name, current_temp,
    )
    return WeatherSyncResult(
        status       = "ok",
        event_id     = event_id,
        fetched_at   = now,
        current_temp = current_temp,
    )


__all__ = ["WeatherSyncResult", "fetch_and_store_for_event"]
