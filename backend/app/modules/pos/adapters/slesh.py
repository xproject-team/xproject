"""Slesh adapter — real implementation.

Composes the four lower layers into a working, read-only Slesh client:

    SleshHTTPClient (client.py)   ── HTTPS transport, bearer auth
        │                            (read-only by construction)
        ├─ TokenBucketLimiter      ── stays under Slesh's quota
        │  (limiter.py)
        ├─ RetryPolicy +           ── exponential backoff on 429/5xx
        │  CircuitBreaker             + circuit breaker after 5 consecutive
        │  (retry.py)                   failures (60s cooldown, 1 probe)
        │
        ├─ Pydantic schemas        ── lenient + log strategy on parse
        │  (schemas.py)
        │
        └─ Pagination helpers      ── two explicit code paths:
                                       _get_paginated() for shops & orders
                                       _get_list()       for categories & products

USAGE (production):
    async with SleshAdapter(
        token=settings.slesh_api_token,
        brand_id=settings.slesh_brand_id,
        base_url=settings.slesh_base_url,
    ) as adapter:
        brand = await adapter.verify_token()
        shops = await adapter.list_shops()
        async for order in adapter.list_orders(since, until):
            ...

USAGE (tests — dependency injection):
    adapter = SleshAdapter.from_components(
        client=mock_client, limiter=mock_limiter,
        breaker=fresh_breaker, brand_id="...",
    )

DESIGN CHOICES (locked in B3 §"Three small design questions"):
- Primitive constructor (token + brand_id + base_url) — one canonical shape.
- Async context manager — closes the underlying httpx client on exit.
- brand_id auto-injected — the adapter is bound to one brand for its lifetime.
- Pagination is EXPLICIT (Option B): two helpers, named for what they do.

Spec: docs/slesh-integration-roadmap.md §B3.5
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Self

from app.modules.pos.adapters.base import BasePOSAdapter
from app.modules.pos.client import SleshHTTPClient
from app.modules.pos.converters import datetime_to_unix_ms
from app.modules.pos.limiter import TokenBucketLimiter
from app.modules.pos.retry import (
    CircuitBreaker,
    RetryPolicy,
    retry_with_backoff,
)
from app.modules.pos.schemas import (
    Brand,
    Category,
    Order,
    Product,
    Shop,
)

logger = logging.getLogger(__name__)


# Default page size for paginated endpoints. Slesh is comfortable with 100;
# we don't push higher because larger pages = bigger blast radius if the
# response shape changes mid-flight.
_DEFAULT_PAGE_SIZE = 100


class SleshAdapter(BasePOSAdapter):
    """Read-only client for the Slesh API, bound to a single brand.

    Constructor is the canonical entry point in production code. Tests
    that need to inject mocks should use the `from_components` classmethod.
    """

    # ─── Construction ────────────────────────────────────────────────
    def __init__(
        self,
        *,
        token:               str,
        brand_id:            str,
        base_url:            str   = "https://api.slesh.it/api",
        request_timeout:     float = 10.0,
        rate_limit_rps:      int   = 5,
        max_retries:         int   = 3,
    ):
        if not brand_id:
            raise ValueError("SleshAdapter requires a non-empty brand_id")

        self._brand_id = brand_id
        self._client   = SleshHTTPClient(
            token    = token,
            base_url = base_url,
            timeout  = request_timeout,
        )
        self._limiter = TokenBucketLimiter(rate_per_sec=rate_limit_rps)
        self._policy  = RetryPolicy(max_retries=max_retries)
        self._breaker = CircuitBreaker()

    @classmethod
    def from_components(
        cls,
        *,
        client:   SleshHTTPClient,
        brand_id: str,
        limiter:  TokenBucketLimiter | None = None,
        breaker:  CircuitBreaker      | None = None,
        policy:   RetryPolicy         | None = None,
    ) -> SleshAdapter:
        """Construct from pre-built dependencies — for tests with mocks.

        Bypasses the regular __init__ to allow injection of mock clients,
        custom breakers (e.g. shared across tests), or specific policies.
        """
        if not brand_id:
            raise ValueError("SleshAdapter requires a non-empty brand_id")

        instance = cls.__new__(cls)
        instance._brand_id = brand_id
        instance._client   = client
        instance._limiter  = limiter or TokenBucketLimiter(rate_per_sec=5)
        instance._policy   = policy  or RetryPolicy()
        instance._breaker  = breaker or CircuitBreaker()
        return instance

    # ─── Async context manager (closes httpx on exit) ────────────────
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # ─── Public API — the 5 read methods from BasePOSAdapter ─────────
    async def verify_token(self) -> Brand:
        """Health check. Returns the brand record bound to our token."""
        raw = await self._call("/brand/my", op_name="verify_token")
        # /brand/my returns a one-element LIST (not a dict). Unwrap it.
        if isinstance(raw, list):
            if not raw:
                raise ValueError("Slesh /brand/my returned an empty list")
            raw = raw[0]
        return Brand.model_validate(raw)

    async def list_shops(
        self,
        experience_id: str | None = None,
    ) -> list[Shop]:
        docs = await self._get_paginated(
            "/shop/my",
            params={"experienceId": experience_id},
            op_name="list_shops",
        )
        return [Shop.model_validate(d) for d in docs]

    async def list_categories(
        self,
        experience_id: str | None = None,
    ) -> list[Category]:
        items = await self._get_list(
            "/category/my",
            params={"experienceId": experience_id},
            op_name="list_categories",
        )
        return [Category.model_validate(c) for c in items]

    async def list_products(
        self,
        experience_id:   str | None = None,
        *,
        populated_field: str | None = None,
    ) -> list[Product]:
        items = await self._get_list(
            "/product/my",
            params={
                "experienceId":   experience_id,
                "populatedField": populated_field,
            },
            op_name="list_products",
        )
        return [Product.model_validate(p) for p in items]

    async def list_orders(
        self,
        since_ts:      datetime,
        until_ts:      datetime,
        *,
        experience_id: str | None = None,
        shop_id:       str | None = None,
        order_type:    str | None = "experience",
    ) -> AsyncIterator[Order]:
        """Stream parsed Order models in the [since_ts, until_ts] window.

        Async generator — caller iterates with `async for`. Pagination is
        handled transparently; caller never sees cursors. Time bounds are
        converted to Unix-ms at the boundary as Slesh requires.
        """
        params = {
            "fromTs":       datetime_to_unix_ms(since_ts),
            "toTs":         datetime_to_unix_ms(until_ts),
            "experienceId": experience_id,
            "shopId":       shop_id,
            "orderType":    order_type,
            "sortDir":      "asc",       # oldest-first for deterministic ingestion
        }
        async for doc in self._iter_paginated("/order/brand-my", params=params, op_name="list_orders"):
            yield Order.model_validate(doc)

    # ─── Internals: pagination + the orchestration sandwich ──────────
    async def _call(
        self,
        path: str,
        *,
        params:  dict[str, Any] | None = None,
        op_name: str,
    ) -> Any:
        """Single call with the full safety stack: limit + retry + breaker."""
        # Inject brand_id into every request — the adapter is brand-bound
        full_params = {"brandId": self._brand_id, **(params or {})}

        async def _do_call() -> Any:
            await self._limiter.acquire()
            return await self._client.get(path, params=full_params)

        return await retry_with_backoff(
            _do_call,
            policy=self._policy,
            breaker=self._breaker,
            op_name=op_name,
        )

    async def _get_list(
        self,
        path: str,
        *,
        params:  dict[str, Any] | None = None,
        op_name: str,
    ) -> list[Any]:
        """For endpoints that return a plain list (categories, products)."""
        raw = await self._call(path, params=params, op_name=op_name)
        if not isinstance(raw, list):
            raise TypeError(
                f"Expected list response from {path}, got {type(raw).__name__}. "
                f"Slesh changed their API shape — investigate."
            )
        return raw

    async def _get_paginated(
        self,
        path: str,
        *,
        params:    dict[str, Any] | None = None,
        page_size: int = _DEFAULT_PAGE_SIZE,
        op_name:   str,
    ) -> list[Any]:
        """For endpoints that paginate via {docs, total, hasNextPage} envelope.

        Walks all pages, returns the full list. Use _iter_paginated() for
        streaming behavior when the result set may be very large.
        """
        all_docs: list[Any] = []
        async for doc in self._iter_paginated(path, params=params, page_size=page_size, op_name=op_name):
            all_docs.append(doc)
        return all_docs

    async def _iter_paginated(
        self,
        path: str,
        *,
        params:    dict[str, Any] | None = None,
        page_size: int = _DEFAULT_PAGE_SIZE,
        op_name:   str,
    ) -> AsyncIterator[Any]:
        """Async-iterator version of pagination — yields one doc at a time.

        Walks pages forward via Slesh's `from` offset. Stops when
        `hasNextPage` is false or the response is malformed.
        """
        # Slesh's `from` is 1-indexed inclusive (minimum 1). We compute the
        # next page's offset ourselves rather than trusting `envelope.to`,
        # which has caused infinite loops in production (Slesh sometimes
        # ignores `from` if it is mid-page-range and re-serves the same
        # first 100 docs, producing 778K idempotency-replays for ~300
        # distinct orders — see B7 debugging journal).
        total_seen      = 0
        page            = 0
        last_first_id: str | None = None
        while True:
            page_params: dict[str, Any] = {
                **(params or {}),
                "pageSize": page_size,
            }
            # First page: omit `from` (Slesh requires from >= 1; from=0 errors).
            # Subsequent pages: 1-indexed start = total_seen + 1.
            if total_seen > 0:
                page_params["from"] = total_seen + 1

            envelope = await self._call(path, params=page_params, op_name=f"{op_name}#p{page}")

            if not isinstance(envelope, dict):
                raise TypeError(
                    f"Expected paginated dict response from {path}, "
                    f"got {type(envelope).__name__}. Slesh shape change — investigate."
                )

            docs = envelope.get("docs", [])

            # Defensive infinite-loop guard: if Slesh ignores `from` and
            # re-serves the same first doc as the previous page, stop.
            if docs and page > 0:
                first_id = docs[0].get("_id") if isinstance(docs[0], dict) else None
                if first_id is not None and first_id == last_first_id:
                    logger.warning(
                        "%s pagination loop detected at page %d: "
                        "first doc id %s repeated. Stopping to avoid loop.",
                        op_name, page, first_id,
                    )
                    return
                last_first_id = first_id
            elif docs:
                last_first_id = docs[0].get("_id") if isinstance(docs[0], dict) else None

            for d in docs:
                yield d
            total_seen += len(docs)

            if not envelope.get("hasNextPage"):
                logger.debug("%s pagination complete: %d pages, total=%s",
                             op_name, page + 1, envelope.get("total"))
                return

            page  += 1
            if not docs:
                # Defensive: hasNextPage=true but no docs returned.
                # Stop to avoid an infinite loop.
                logger.warning("%s pagination stalled at page %d (no docs but hasNextPage=true)",
                               op_name, page)
                return


__all__ = ["SleshAdapter"]
