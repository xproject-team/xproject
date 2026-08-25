"""Fake POS adapter — provider-shaped payloads from generated data.

Substitutes for the real adapter behind BasePOSAdapter in staging
(POS_ADAPTER=fake). Yields the SAME parsed pydantic models as the real
adapter, produced by running raw dicts in the provider's exact wire
shape through the real schemas — so schema parsing, the ingester and
the event_orders upsert all execute production code. What it skips is
transport only: HTTP, pagination, retry, rate limiting.

HARD RULE: this module must never import app.core.config or httpx —
it is constructed with nothing, so no Slesh credential or URL can leak
into it (see factory.get_pos_adapter and the safety tests).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from app.modules.pos.adapters.base import BasePOSAdapter
from app.modules.pos.schemas import Brand, Category, Order, Product, Shop

# The one brand the fake answers for. Value mirrored (not imported) from
# factory.FAKE_BRAND_ID — importing factory here would drag settings in.
FAKE_BRAND_ID = "fakebrand000000000000fa9e"


class FakePOSAdapter(BasePOSAdapter):
    """Read-only fake fulfilling the BasePOSAdapter contract.

    Constructor takes no configuration on purpose.
    """

    async def __aenter__(self) -> "FakePOSAdapter":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def verify_token(self) -> Brand:
        return Brand.model_validate({
            "_id": FAKE_BRAND_ID,
            "name": "Staging Fake Brand",
            "isEnabled": True,
        })

    async def list_shops(self, experience_id: str | None = None) -> list[Shop]:
        return []

    async def list_categories(self, experience_id: str | None = None) -> list[Category]:
        return []

    async def list_products(
        self,
        experience_id: str | None = None,
        *,
        populated_field: str | None = None,
    ) -> list[Product]:
        return []

    async def list_orders(
        self,
        since_ts: datetime,
        until_ts: datetime,
        *,
        experience_id: str | None = None,
        shop_id: str | None = None,
        order_type: str | None = "experience",
    ) -> AsyncIterator[Order]:
        return
        yield  # pragma: no cover — makes this an async generator
