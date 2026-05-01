"""HTTP transport layer for Slesh API — read-only by construction.

This module is the THINNEST possible httpx wrapper. It does exactly four
things and nothing else:

  1. Holds an httpx.AsyncClient with bearer auth + JSON headers
  2. Exposes `get()` — the only HTTP verb we ever use
  3. Parses JSON responses into Python dicts/lists
  4. Maps non-2xx status codes to typed exceptions

EXPLICIT NON-FEATURES (each lives in a separate file by design):
  - Rate limiting    → app.modules.pos.limiter
  - Retry logic      → app.modules.pos.retry
  - Pagination       → app.modules.pos.adapters.slesh (business layer)
  - Schema parsing   → app.modules.pos.schemas

WHY READ-ONLY BY CONSTRUCTION:
The only public method is `get()`. There is no `post()`, `put()`, `delete()`,
or `patch()`. This makes it physically impossible for our code to mutate
Slesh data, even by accident. We are observers; Slesh is the source of truth.

USAGE:
    async with SleshHTTPClient(token=..., base_url=..., timeout=10.0) as c:
        data = await c.get("/brand/my")
        shops = await c.get("/shop/my", params={"brandId": "xxx", "pageSize": 20})

Spec: docs/slesh-integration-roadmap.md §B3.2
"""
from __future__ import annotations

import logging
from typing import Any, Self

import httpx

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Typed exceptions — callers can catch specifically what they care about
# ─────────────────────────────────────────────────────────────────────
class SleshHTTPError(Exception):
    """Base class for all Slesh HTTP-related errors."""
    def __init__(self, message: str, *, status_code: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.url         = url


class SleshAuthError(SleshHTTPError):
    """401/403 — token rejected. Probably needs rotation. Don't retry."""


class SleshRateLimitError(SleshHTTPError):
    """429 — we've been rate-limited. Caller (retry layer) decides backoff."""


class SleshServerError(SleshHTTPError):
    """5xx — Slesh's problem, retryable. Caller should back off and retry."""


class SleshClientError(SleshHTTPError):
    """4xx (other) — request was malformed. Don't retry; fix the call."""


# ─────────────────────────────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────────────────────────────
class SleshHTTPClient:
    """Thin async httpx wrapper for the Slesh API.

    Use as an async context manager so the underlying httpx client is
    closed cleanly even if an exception is raised mid-flight.
    """

    def __init__(
        self,
        *,
        token:    str,
        base_url: str,
        timeout:  float = 10.0,
    ):
        if not token:
            raise ValueError("SleshHTTPClient requires a non-empty token")
        if not base_url:
            raise ValueError("SleshHTTPClient requires a non-empty base_url")

        self._base_url = base_url.rstrip("/")
        # Force IPv4-only outbound. Slesh is Cloudflare-fronted; on some
        # networks (notably institutional Wi-Fi) IPv6 routing to Cloudflare
        # is half-broken and triggers 'Connection reset by peer' on async
        # DNS resolution. curl handles this via happy-eyeballs fallback,
        # but Python's asyncio doesn't. Forcing IPv4 sidesteps the issue
        # entirely; it is a no-op on production servers where IPv6 works.
        ipv4_transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
        self._client   = httpx.AsyncClient(
            base_url  = self._base_url,
            transport = ipv4_transport,
            headers   = {
                "Authorization": f"Bearer {token}",
                "Accept":        "application/json",
                "User-Agent":    "XProject-Slesh-Adapter/1.0",
            },
            timeout   = httpx.Timeout(timeout),
            # See note above on trust_env: avoid inheriting laptop-local
            # debugging proxies or stale macOS Wi-Fi proxy state.
            trust_env = False,
        )

    # ── Async context manager support ────────────────────────────────
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying httpx client. Idempotent."""
        await self._client.aclose()

    # ── The ONE public method — GET. No other verbs exist. ──────────
    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Issue a GET against `path` and return the parsed JSON body.

        Args:
            path:   path relative to base_url (must start with '/')
            params: query-string parameters; None values are dropped.

        Returns:
            Parsed JSON: dict for envelope responses, list for plain-list
            endpoints (categories / products), depending on the endpoint.

        Raises:
            SleshAuthError      on 401 / 403
            SleshRateLimitError on 429
            SleshClientError    on other 4xx
            SleshServerError    on 5xx
            httpx.RequestError  on network-level failures (DNS, timeout, etc.)
        """
        # Drop None-valued params so callers can pass conditional filters
        # without manually filtering: e.g. params={"experienceId": maybe_none}
        clean_params = (
            {k: v for k, v in params.items() if v is not None}
            if params else None
        )

        try:
            response = await self._client.get(path, params=clean_params)
        except httpx.RequestError as exc:
            # Network-level failure (DNS, connection refused, timeout, etc.)
            # We let it propagate — retry layer above us decides what to do.
            logger.warning("Slesh GET %s network error: %s", path, exc)
            raise

        return self._handle_response(response, path)

    # ── Internal: status-code dispatch ───────────────────────────────
    def _handle_response(self, resp: httpx.Response, path: str) -> Any:
        """Map the response to either parsed JSON or a typed exception."""
        sc = resp.status_code

        if 200 <= sc < 300:
            try:
                return resp.json()
            except ValueError as exc:
                # Slesh sent 2xx but body wasn't JSON. Treat as client-side.
                raise SleshClientError(
                    f"Slesh returned {sc} with non-JSON body",
                    status_code=sc, url=path,
                ) from exc

        # Build a useful error message; trim long bodies aggressively.
        body_preview = (resp.text or "")[:200]

        if sc in (401, 403):
            raise SleshAuthError(
                f"Slesh auth failed ({sc}) on {path}: {body_preview}",
                status_code=sc, url=path,
            )
        if sc == 429:
            raise SleshRateLimitError(
                f"Slesh rate limit hit on {path}: {body_preview}",
                status_code=sc, url=path,
            )
        if 400 <= sc < 500:
            raise SleshClientError(
                f"Slesh client error {sc} on {path}: {body_preview}",
                status_code=sc, url=path,
            )
        if 500 <= sc < 600:
            raise SleshServerError(
                f"Slesh server error {sc} on {path}: {body_preview}",
                status_code=sc, url=path,
            )

        # Anything else (1xx, 3xx, weirdness) — defensive fallback
        raise SleshHTTPError(
            f"Slesh unexpected status {sc} on {path}: {body_preview}",
            status_code=sc, url=path,
        )


__all__ = [
    "SleshHTTPClient",
    "SleshHTTPError",
    "SleshAuthError",
    "SleshRateLimitError",
    "SleshClientError",
    "SleshServerError",
]
