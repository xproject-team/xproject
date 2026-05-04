"""WeatherAdapter — Open-Meteo HTTP client.

Same architectural pattern as the Slesh adapter:
- Thin httpx wrapper (single GET method)
- IPv4-only transport (sidesteps the Cloudflare/IPv6 issue we hit on
  institutional networks during Slesh integration)
- Retry policy with circuit breaker (reused from pos.retry — generic,
  not Slesh-specific)
- trust_env=False (ignore stale local proxy state)

Open-Meteo specifics:
- No API key needed (public free tier, fair-use only)
- No auth headers required
- Rate limit ~10k requests/day per IP — far above what one event needs
- Single endpoint: GET /v1/forecast?latitude&longitude&hourly&current

We deliberately do NOT subclass BasePOSAdapter (that contract is for
POS systems with shops/products/orders semantics). Weather is its own
external system, with its own minimal contract: fetch_forecast(lat, lon).

Spec: docs/slesh-integration-roadmap.md (Phase B - Weather Integration).
"""
from __future__ import annotations

import logging
from typing import Self

import httpx

from app.modules.pos.retry import (
    CircuitBreaker,
    RetryPolicy,
    retry_with_backoff,
)
from app.modules.weather.schemas import ForecastResponse

logger = logging.getLogger(__name__)


# Default Open-Meteo base URL. Public, free, no key.
_DEFAULT_BASE_URL = "https://api.open-meteo.com/v1"

# Default fields we always request. Tuned for our dashboard pill +
# post-event report use-case. If you need more, pass extra=... on
# fetch_forecast — but consider whether the snapshot column needs
# a migration to surface them.
_DEFAULT_HOURLY_FIELDS = (
    "temperature_2m,"
    "precipitation,"
    "precipitation_probability,"
    "weather_code,"
    "wind_speed_10m"
)
_DEFAULT_CURRENT_FIELDS = (
    "temperature_2m,"
    "weather_code,"
    "relative_humidity_2m,"
    "wind_speed_10m,"
    "precipitation"
)


# ── Typed exceptions ────────────────────────────────────────────────
class WeatherHTTPError(Exception):
    """Base for all weather adapter errors."""
    def __init__(self, msg: str, *, status_code: int | None = None) -> None:
        super().__init__(msg)
        self.status_code = status_code


class WeatherClientError(WeatherHTTPError):
    """4xx (other than 429) — request shape is wrong; do not retry."""


class WeatherRateLimitError(WeatherHTTPError):
    """429 — we hit Open-Meteo\'s rate limit. Retry layer handles backoff."""


class WeatherServerError(WeatherHTTPError):
    """5xx — Open-Meteo problem. Retryable."""


_RETRYABLE: tuple[type[BaseException], ...] = (
    WeatherRateLimitError,
    WeatherServerError,
    httpx.RequestError,
)


# ── Adapter ────────────────────────────────────────────────────────
class WeatherAdapter:
    """Async client for Open-Meteo forecasts.

    Use as an async context manager so the underlying httpx client is
    closed cleanly even on exception.
    """

    def __init__(
        self,
        *,
        base_url:        str   = _DEFAULT_BASE_URL,
        request_timeout: float = 10.0,
        max_retries:     int   = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._policy   = RetryPolicy(max_retries=max_retries)
        self._breaker  = CircuitBreaker()

        # IPv4-only transport — same fix that unblocked Slesh on
        # institutional networks (Cloudflare-fronted services + asyncio
        # sometimes hit "Connection reset by peer" via IPv6).
        ipv4_transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")

        self._client = httpx.AsyncClient(
            base_url  = self._base_url,
            transport = ipv4_transport,
            headers   = {
                "Accept":     "application/json",
                "User-Agent": "XProject-WeatherAdapter/1.0",
            },
            timeout   = httpx.Timeout(request_timeout),
            trust_env = False,
        )

    # ── Context manager support ───────────────────────────────────
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # ── Public API ────────────────────────────────────────────────
    async def fetch_forecast(
        self,
        *,
        latitude:     float,
        longitude:    float,
        timezone:     str = "Europe/Rome",
        forecast_days: int = 2,
    ) -> ForecastResponse:
        """Fetch the current weather + N-day hourly forecast for (lat, lon).

        Args:
            latitude / longitude: WGS84 decimal degrees.
            timezone: IANA name; Open-Meteo localises hourly.time strings to it.
            forecast_days: how many days to fetch (1-16; we default 2).

        Returns:
            ForecastResponse parsed from the JSON body.

        Raises:
            WeatherClientError / RateLimitError / ServerError as appropriate.
            httpx.RequestError on network-level failures (DNS, timeout).
        """
        params: dict = {
            "latitude":      latitude,
            "longitude":     longitude,
            "hourly":        _DEFAULT_HOURLY_FIELDS,
            "current":       _DEFAULT_CURRENT_FIELDS,
            "timezone":      timezone,
            "forecast_days": forecast_days,
        }

        async def _do_call() -> dict:
            try:
                resp = await self._client.get("/forecast", params=params)
            except httpx.RequestError as exc:
                logger.warning("weather GET /forecast network error: %s", exc)
                raise

            return self._handle_response(resp)

        raw = await retry_with_backoff(
            _do_call,
            policy=self._policy,
            breaker=self._breaker,
            op_name=f"fetch_forecast({latitude},{longitude})",
        )
        return ForecastResponse.model_validate(raw)

    # ── Internal: status-code dispatch ────────────────────────────
    def _handle_response(self, resp: httpx.Response) -> dict:
        sc = resp.status_code
        if 200 <= sc < 300:
            try:
                return resp.json()
            except ValueError as exc:
                raise WeatherClientError(
                    f"Open-Meteo returned {sc} with non-JSON body",
                    status_code=sc,
                ) from exc

        body_preview = (resp.text or "")[:200]
        if sc == 429:
            raise WeatherRateLimitError(
                f"Open-Meteo rate limit hit: {body_preview}",
                status_code=sc,
            )
        if 400 <= sc < 500:
            raise WeatherClientError(
                f"Open-Meteo client error {sc}: {body_preview}",
                status_code=sc,
            )
        if 500 <= sc < 600:
            raise WeatherServerError(
                f"Open-Meteo server error {sc}: {body_preview}",
                status_code=sc,
            )
        raise WeatherHTTPError(
            f"Open-Meteo unexpected status {sc}: {body_preview}",
            status_code=sc,
        )


__all__ = [
    "WeatherAdapter",
    "WeatherHTTPError",
    "WeatherClientError",
    "WeatherRateLimitError",
    "WeatherServerError",
]
