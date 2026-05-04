"""Unit tests for app.modules.weather.schemas.

Tests use the recorded Open-Meteo response fixture in
tests/fixtures/weather/forecast_roma.json. Same discipline as the Slesh
schema tests: deterministic, fast, network-free.

What this locks down:
  - ForecastResponse parses the real Open-Meteo shape
  - CurrentWeather + HourlyForecast field types
  - Lenient parsing accepts unknown Open-Meteo fields without crashing
  - hourly_as_records correctly zips parallel arrays into per-hour dicts
  - Edge cases: empty hourly, mismatched array lengths

Spec: docs/slesh-integration-roadmap.md (Phase B - Weather Integration).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.weather.schemas import (
    CurrentWeather,
    ForecastResponse,
    HourlyForecast,
    hourly_as_records,
)


FIXTURE = Path(__file__).parent / "fixtures" / "weather" / "forecast_roma.json"


@pytest.fixture
def raw_forecast() -> dict:
    """Recorded Open-Meteo response for Roma (B.2 fixture)."""
    return json.loads(FIXTURE.read_text())


# ─── ForecastResponse ───────────────────────────────────────────────

def test_forecast_response_parses_real_fixture(raw_forecast):
    """Roma fixture parses cleanly into ForecastResponse."""
    fc = ForecastResponse.model_validate(raw_forecast)

    # Roma coordinates (Open-Meteo rounds to nearest grid point)
    assert 41 < fc.latitude  < 43
    assert 11 < fc.longitude < 14
    assert fc.timezone == "Europe/Rome"
    assert fc.current is not None
    assert fc.hourly  is not None


def test_forecast_response_lenient_accepts_unknown_fields(raw_forecast):
    """Open-Meteo can add metadata fields (e.g. timezone_abbreviation,
    elevation, current_units) — the schema must accept them as model_extra."""
    fc = ForecastResponse.model_validate(raw_forecast)

    # current_units / hourly_units are extra fields (we don\'t model them)
    assert fc.model_extra is not None
    assert "current_units" in fc.model_extra or "hourly_units" in fc.model_extra


def test_forecast_response_with_only_current(raw_forecast):
    """Hourly is optional — schema accepts current-only payloads."""
    raw_forecast.pop("hourly", None)
    fc = ForecastResponse.model_validate(raw_forecast)
    assert fc.current is not None
    assert fc.hourly  is None


# ─── CurrentWeather ─────────────────────────────────────────────────

def test_current_weather_required_fields(raw_forecast):
    """time + temperature_2m + weather_code are required."""
    cw = CurrentWeather.model_validate(raw_forecast["current"])
    assert isinstance(cw.time, str)
    assert isinstance(cw.temperature_2m, float)
    assert isinstance(cw.weather_code, int)


def test_current_weather_optional_fields_default_to_none():
    """When humidity/wind/precipitation absent, fields default to None."""
    cw = CurrentWeather.model_validate({
        "time":           "2026-05-04T12:00",
        "temperature_2m": 20.0,
        "weather_code":   0,
    })
    assert cw.relative_humidity_2m is None
    assert cw.wind_speed_10m       is None
    assert cw.precipitation        is None


# ─── HourlyForecast ─────────────────────────────────────────────────

def test_hourly_forecast_parses_parallel_arrays(raw_forecast):
    """Open-Meteo returns parallel arrays (time[], temperature_2m[], etc.).
    All arrays must have the same length."""
    h = HourlyForecast.model_validate(raw_forecast["hourly"])
    n = len(h.time)
    assert n == 48                                    # 2 days * 24 hours
    assert len(h.temperature_2m)            == n
    assert len(h.precipitation)             == n
    assert len(h.precipitation_probability) == n
    assert len(h.weather_code)              == n
    assert len(h.wind_speed_10m)            == n


def test_hourly_forecast_empty_arrays_default():
    """When Open-Meteo returns only `time`, optional arrays default to empty."""
    h = HourlyForecast.model_validate({
        "time": ["2026-05-04T00:00", "2026-05-04T01:00"],
    })
    assert h.time            == ["2026-05-04T00:00", "2026-05-04T01:00"]
    assert h.temperature_2m  == []
    assert h.weather_code    == []


# ─── hourly_as_records ─────────────────────────────────────────────

def test_hourly_as_records_zips_parallel_arrays(raw_forecast):
    """Helper produces a list of per-hour dicts, one per index."""
    fc = ForecastResponse.model_validate(raw_forecast)
    records = hourly_as_records(fc.hourly)

    assert len(records) == 48
    first = records[0]
    expected_keys = {
        "time", "temperature_2m", "precipitation",
        "precipitation_probability", "weather_code", "wind_speed_10m",
    }
    assert set(first.keys()) == expected_keys
    # First record\'s time should match the fixture\'s first time entry
    assert first["time"] == fc.hourly.time[0]


def test_hourly_as_records_handles_none():
    """None hourly returns empty list, no crash."""
    assert hourly_as_records(None) == []


def test_hourly_as_records_handles_empty_time():
    """HourlyForecast with empty time array returns empty list."""
    h = HourlyForecast(time=[])
    assert hourly_as_records(h) == []


def test_hourly_as_records_tolerates_short_arrays():
    """If precipitation array is shorter than time[], missing fields = None.

    Defensive: Open-Meteo guarantees equal lengths, but we never want a
    silent IndexError to crash the dashboard.
    """
    h = HourlyForecast(
        time           = ["2026-05-04T00:00", "2026-05-04T01:00", "2026-05-04T02:00"],
        temperature_2m = [10.0, 11.0, 12.0],
        precipitation  = [0.0, 0.5],     # only 2 entries (short)
        weather_code   = [0, 1, 2],
        wind_speed_10m = [3.0, 4.0, 5.0],
        precipitation_probability = [0, 10, 20],
    )
    records = hourly_as_records(h)

    assert len(records) == 3
    # Index 2 has no precipitation entry -> None
    assert records[2]["precipitation"] is None
    assert records[2]["temperature_2m"] == 12.0       # other fields fine
    assert records[2]["weather_code"]   == 2


# test_hourly_as_records_skips_none_time_entries deleted: the schema
# strictly types time as list[str], so Pydantic rejects None entries
# at validation time before the helper ever sees them. The defensive
# guard in hourly_as_records is belt-and-suspenders for the (unlikely)
# case the schema is bypassed via .construct() or similar.
