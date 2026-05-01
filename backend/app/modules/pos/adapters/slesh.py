"""Slesh adapter — concrete implementation of BasePOSAdapter for the Slesh API.

This is a SKELETON. The five methods below conform to the contract defined
in `base.py` but are not yet wired to the network. Real httpx-based
implementation lands in B3 (`feat/slesh-b3-adapter-impl`), where each
method gets:

  - rate limiting (token bucket, configurable via settings.slesh_rate_limit_rps)
  - exponential backoff retry on 429/5xx
  - circuit breaker after N consecutive errors
  - pagination handling for shops/orders (docs envelope)
  - direct list parsing for categories/products (plain list)

Why a skeleton instead of leaving the methods undeclared:
B2 ships valid, importable code. A subclass with ABC stubs unimplemented
would import, but instantiating it would raise a cryptic Pydantic-style
TypeError. By declaring the methods explicitly here, the failure mode
during the B2-to-B3 gap is a clear NotImplementedError with a message
pointing the reader at B3.

Spec reference: docs/slesh-integration-roadmap.md §B2.7 (skeleton) and §B3
(real implementation).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from app.modules.pos.adapters.base import BasePOSAdapter
from app.modules.pos.schemas import (
    Brand,
    Category,
    Order,
    Product,
    Shop,
)


_NOT_YET = "Slesh adapter method ships in B3 (feat/slesh-b3-adapter-impl)"


class SleshAdapter(BasePOSAdapter):
    """Read-only client for Slesh API. Skeleton — see module docstring.

    All five methods raise NotImplementedError with a clear message until
    B3 lands. This is intentional: the class is fully importable and
    type-checks correctly, so downstream code (POSService, tests, type
    hints) can reference it. Only actual *invocation* fails.
    """

    async def verify_token(self) -> Brand:
        raise NotImplementedError(_NOT_YET + " — verify_token")

    async def list_shops(
        self,
        experience_id: str | None = None,
    ) -> list[Shop]:
        raise NotImplementedError(_NOT_YET + " — list_shops")

    async def list_categories(
        self,
        experience_id: str | None = None,
    ) -> list[Category]:
        raise NotImplementedError(_NOT_YET + " — list_categories")

    async def list_products(
        self,
        experience_id: str | None = None,
    ) -> list[Product]:
        raise NotImplementedError(_NOT_YET + " — list_products")

    async def list_orders(
        self,
        since_ts:      datetime,
        until_ts:      datetime,
        *,
        experience_id: str | None = None,
        shop_id:       str | None = None,
        order_type:    str | None = "experience",
    ) -> AsyncIterator[Order]:
        raise NotImplementedError(_NOT_YET + " — list_orders")
        # The next line is unreachable; it exists to satisfy the static
        # analyser that this is an async generator returning Order.
        yield  # type: ignore[unreachable]
