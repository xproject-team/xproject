"""Pydantic schemas for Open-Meteo forecast responses.

Open-Meteo returns hourly data as PARALLEL ARRAYS (time[], temperature_2m[],
precipitation[], etc.) rather than a list of dicts. This is unusual; we
keep the raw shape in our base schema and provide a helper to zip into
list[HourlyPoint] when the consumer wants per-hour iteration.

We use lenient parsing (extra="allow") because Open-Meteo occasionally
returns extra metadata fields we don\'t care about. Same discipline
that survived Slesh\'s schema drift.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _OpenMeteoModel(BaseModel):
    """Base — lenient parsing of unknown fields (logged but accepted)."""
    model_config = ConfigDict(extra="allow")


class CurrentWeather(_OpenMeteoModel):
    """The current snapshot returned in the `current` block."""
    time:                str
    temperature_2m:      float
    weather_code:        int
    relative_humidity_2m: int | None = None
    wind_speed_10m:      float | None = None
    precipitation:       float | None = None


class HourlyForecast(_OpenMeteoModel):
    """Parallel arrays. Index N across all arrays = same hour.

    Length is always equal across arrays. Open-Meteo guarantees this.
    """
    time:                     list[str]
    temperature_2m:           list[float] = Field(default_factory=list)
    precipitation:            list[float] = Field(default_factory=list)
    precipitation_probability: list[int] = Field(default_factory=list)
    weather_code:             list[int]   = Field(default_factory=list)
    wind_speed_10m:           list[float] = Field(default_factory=list)


class ForecastResponse(_OpenMeteoModel):
    """Full Open-Meteo forecast response."""
    latitude:           float
    longitude:          float
    timezone:           str = "UTC"
    timezone_abbreviation: str | None = None
    elevation:          float | None  = None
    utc_offset_seconds: int | None    = None
    current:            CurrentWeather | None = None
    hourly:             HourlyForecast | None = None


def hourly_as_records(h: HourlyForecast | None) -> list[dict]:
    """Convert HourlyForecast (parallel arrays) into per-hour dicts."""
    if h is None or not h.time:
        return []
    return [
        {
            "time":                      h.time[i],
            "temperature_2m":            h.temperature_2m[i]            if i < len(h.temperature_2m)            else None,
            "precipitation":             h.precipitation[i]             if i < len(h.precipitation)             else None,
            "precipitation_probability": h.precipitation_probability[i] if i < len(h.precipitation_probability) else None,
            "weather_code":              h.weather_code[i]              if i < len(h.weather_code)              else None,
            "wind_speed_10m":            h.wind_speed_10m[i]            if i < len(h.wind_speed_10m)            else None,
        }
        for i in range(len(h.time))
        if h.time[i] is not None
    ]


__all__ = [
    "CurrentWeather",
    "HourlyForecast",
    "ForecastResponse",
    "hourly_as_records",
]
