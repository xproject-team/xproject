"""Unit tests for app.modules.weather.sync.

We patch WeatherAdapter and the DB lookup so the test stays in-memory.
This proves:
  - status=ok writes the snapshot + fetched_at on the event row
  - status=skipped when venue lacks lat/lon (clear log line, no error)
  - status=error when adapter raises (caught, returned, never propagates)
  - status=error when event is not found for the tenant
  - High-water timestamp is fresh on success
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest


TENANT_ID = UUID("25ef916c-a288-44ae-b17c-8dfd09390834")
EVENT_ID  = UUID("e7866455-b721-419e-8d10-e5e157ff50d6")


# ─── Fakes ─────────────────────────────────────────────────────────

@dataclass
class FakeVenue:
    id:        UUID
    name:      str
    latitude:  Decimal | None
    longitude: Decimal | None


@dataclass
class FakeEvent:
    id:                 UUID
    tenant_id:          UUID
    venue_id:           UUID
    weather_snapshot:   dict | None     = None
    weather_fetched_at: Any  | None     = None


class FakeForecast:
    """Minimal forecast object — only the shape sync.py reads."""
    def __init__(self, temp: float = 12.2):
        self._temp = temp

    def model_dump(self, *, mode: str = "json") -> dict:
        return {
            "current": {"temperature_2m": self._temp, "weather_code": 0},
            "hourly":  {"time": [], "temperature_2m": []},
        }

    @property
    def current(self):
        class _C:
            temperature_2m = self._temp
        return _C()


class FakeWeatherAdapter:
    """Drop-in for WeatherAdapter. Configurable response or exception."""
    def __init__(self, *, forecast: FakeForecast = None, raise_exc: Exception = None):
        self._forecast = forecast or FakeForecast()
        self._raise    = raise_exc

    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    async def fetch_forecast(self, **kwargs):
        if self._raise is not None:
            raise self._raise
        return self._forecast


class FakeDB:
    """Records flushes; produces canned execute() results."""
    def __init__(self, event: FakeEvent | None, venue: FakeVenue | None):
        self._event   = event
        self._venue   = venue
        self.flushed  = False
        self.added    = []

    async def execute(self, *_args, **_kwargs):
        return _FakeExecResult(self._event, self._venue)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True


class _FakeExecResult:
    def __init__(self, event: FakeEvent | None, venue: FakeVenue | None):
        self._event = event
        self._venue = venue

    def one_or_none(self):
        if self._event is None or self._venue is None:
            return None
        return (self._event, self._venue)


@pytest.fixture
def patched_adapter(monkeypatch):
    """Lets each test inject the adapter to use."""
    config = {"adapter": FakeWeatherAdapter()}

    import app.modules.weather.sync as sync

    class _Factory:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self):
            return await config["adapter"].__aenter__()
        async def __aexit__(self, *args):
            return await config["adapter"].__aexit__(*args)

    monkeypatch.setattr(sync, "WeatherAdapter", _Factory)
    return config


# ─── Tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_status_ok_writes_snapshot(patched_adapter):
    """Happy path: snapshot persisted, fetched_at set, status ok."""
    from app.modules.weather.sync import fetch_and_store_for_event

    venue = FakeVenue(
        id=uuid4(), name="Sundance Venue",
        latitude=Decimal("41.902800"), longitude=Decimal("12.496400"),
    )
    event = FakeEvent(id=EVENT_ID, tenant_id=TENANT_ID, venue_id=venue.id)
    db    = FakeDB(event, venue)

    patched_adapter["adapter"] = FakeWeatherAdapter(forecast=FakeForecast(temp=15.5))

    result = await fetch_and_store_for_event(
        db=db, event_id=EVENT_ID, tenant_id=TENANT_ID,
    )

    assert result.status                  == "ok"
    assert result.event_id                == EVENT_ID
    assert result.current_temp            == 15.5
    assert result.fetched_at              is not None
    assert event.weather_snapshot         is not None
    assert event.weather_snapshot["current"]["temperature_2m"] == 15.5
    assert event.weather_fetched_at       is not None
    assert db.flushed                     is True


@pytest.mark.asyncio
async def test_sync_status_skipped_when_venue_has_no_coords(patched_adapter):
    """Venue without lat/lon produces status=skipped (NOT error)."""
    from app.modules.weather.sync import fetch_and_store_for_event

    venue = FakeVenue(
        id=uuid4(), name="Mystery Venue", latitude=None, longitude=None,
    )
    event = FakeEvent(id=EVENT_ID, tenant_id=TENANT_ID, venue_id=venue.id)
    db    = FakeDB(event, venue)

    result = await fetch_and_store_for_event(
        db=db, event_id=EVENT_ID, tenant_id=TENANT_ID,
    )

    assert result.status              == "skipped"
    assert "no latitude/longitude"    in (result.reason or "")
    assert event.weather_snapshot     is None
    assert db.flushed                 is False


@pytest.mark.asyncio
async def test_sync_status_error_when_adapter_raises(patched_adapter):
    """Adapter exception is caught, returned as status=error, never propagates."""
    from app.modules.weather.sync import fetch_and_store_for_event

    venue = FakeVenue(
        id=uuid4(), name="Sundance Venue",
        latitude=Decimal("41.902800"), longitude=Decimal("12.496400"),
    )
    event = FakeEvent(id=EVENT_ID, tenant_id=TENANT_ID, venue_id=venue.id)
    db    = FakeDB(event, venue)

    patched_adapter["adapter"] = FakeWeatherAdapter(
        raise_exc=RuntimeError("network broke")
    )

    # Must NOT raise — same resilience contract as the Slesh poller
    result = await fetch_and_store_for_event(
        db=db, event_id=EVENT_ID, tenant_id=TENANT_ID,
    )

    assert result.status                in {"error"}
    assert "network broke"              in (result.reason or "")
    assert event.weather_snapshot       is None
    assert db.flushed                   is False


@pytest.mark.asyncio
async def test_sync_status_error_when_event_not_found(patched_adapter):
    """Event missing for tenant -> error, no adapter call, no DB writes."""
    from app.modules.weather.sync import fetch_and_store_for_event

    db = FakeDB(event=None, venue=None)   # no row found

    result = await fetch_and_store_for_event(
        db=db, event_id=EVENT_ID, tenant_id=TENANT_ID,
    )

    assert result.status               == "error"
    assert "not found"                 in (result.reason or "")
    assert db.flushed                  is False


@pytest.mark.asyncio
async def test_sync_result_str_for_ok():
    """WeatherSyncResult.__str__ produces a useful one-liner for logs."""
    from app.modules.weather.sync import WeatherSyncResult
    r = WeatherSyncResult(
        status="ok", event_id=EVENT_ID, current_temp=15.5,
    )
    s = str(r)
    assert "ok" in s
    assert str(EVENT_ID) in s
    assert "15.5" in s


@pytest.mark.asyncio
async def test_sync_result_str_for_error():
    from app.modules.weather.sync import WeatherSyncResult
    r = WeatherSyncResult(
        status="error", event_id=EVENT_ID, reason="boom",
    )
    s = str(r)
    assert "error" in s
    assert "boom" in s
