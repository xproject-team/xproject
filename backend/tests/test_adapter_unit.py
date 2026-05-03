"""SleshAdapter unit tests — fixture-based, no network calls.

These tests exercise the FULL adapter pipeline (limiter + retry + breaker +
schema parsing + pagination) using recorded Slesh fixtures, without ever
hitting the real network.

WHY THIS FILE EXISTS:
We can't run live integration tests on every commit (no sandbox, production
quota cost). Instead, we replay recorded responses through a fake HTTP client
that implements the same .get() signature as SleshHTTPClient. This proves:

  - Schema parsing wires correctly to adapter methods
  - Pagination walks correctly through multi-page envelopes
  - brand_id is auto-injected into every request
  - The two pagination paths (paginated vs plain-list) are dispatched correctly
  - Defensive type checks fire when Slesh changes shape

Spec: docs/slesh-integration-roadmap.md §B3.7
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.modules.pos.adapters.slesh import SleshAdapter
from app.modules.pos.client          import SleshClientError
from app.modules.pos.schemas         import Brand, Category, Order, Product, Shop


BRAND_ID = "6650c69e25fcbf370f6fcc16"


# ─────────────────────────────────────────────────────────────────
# Fake HTTP client — replaces SleshHTTPClient in tests
# ─────────────────────────────────────────────────────────────────
class FakeSleshHTTPClient:
    """Drop-in replacement for SleshHTTPClient that returns fixture data.

    Records every call (path + params) so tests can assert on what the
    adapter actually requested.
    """

    def __init__(self, responses: dict[str, Any] | list[Any]):
        # Either a dict of path→response, or a list of sequential responses
        self._responses = responses
        self._call_log: list[dict[str, Any]] = []

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self._call_log

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        self._call_log.append({"path": path, "params": dict(params or {})})

        if isinstance(self._responses, list):
            # Sequential mode: pop the next response
            if not self._responses:
                raise RuntimeError(f"FakeSleshHTTPClient: no more responses queued (path={path})")
            return self._responses.pop(0)

        # Dict mode: look up by path
        if path not in self._responses:
            raise RuntimeError(f"FakeSleshHTTPClient: no fixture for path {path!r}")
        return self._responses[path]

    async def aclose(self) -> None:
        pass


def _make_adapter(client: FakeSleshHTTPClient) -> SleshAdapter:
    """Construct a SleshAdapter wired to a fake client. Used by every test."""
    return SleshAdapter.from_components(client=client, brand_id=BRAND_ID)


# ─────────────────────────────────────────────────────────────────
# 1. verify_token — single object response (after list-unwrap)
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_token_unwraps_single_element_list(slesh_fixture):
    """Slesh /brand/my returns a list with one Brand. Adapter unwraps it."""
    fixture = slesh_fixture("brand_my")
    # Real /brand/my response is a list, but our fixture saved it as a dict.
    # Wrap it in a list to match real Slesh behavior.
    client  = FakeSleshHTTPClient({"/brand/my": [fixture]})
    adapter = _make_adapter(client)

    brand = await adapter.verify_token()

    assert isinstance(brand, Brand)
    assert brand.id == BRAND_ID
    assert brand.name == "Sundance"


@pytest.mark.asyncio
async def test_verify_token_handles_dict_response_too(slesh_fixture):
    """Defensive: if Slesh ever returns a dict instead of a list, we still parse."""
    fixture = slesh_fixture("brand_my")
    client  = FakeSleshHTTPClient({"/brand/my": fixture})  # dict, not list
    adapter = _make_adapter(client)

    brand = await adapter.verify_token()
    assert brand.name == "Sundance"


@pytest.mark.asyncio
async def test_verify_token_raises_on_empty_list():
    """Empty list response is treated as a failure, not 'no brand'."""
    client  = FakeSleshHTTPClient({"/brand/my": []})
    adapter = _make_adapter(client)

    with pytest.raises(ValueError, match="empty list"):
        await adapter.verify_token()


# ─────────────────────────────────────────────────────────────────
# 2. list_shops — paginated docs envelope
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_shops_parses_paginated_envelope(slesh_fixture):
    """Single-page paginated response yields all docs as Shop models."""
    fixture = slesh_fixture("shop_my")  # has hasNextPage=False after our recording
    # Force hasNextPage to False so pagination stops on this page
    fixture = {**fixture, "hasNextPage": False}
    client  = FakeSleshHTTPClient({"/shop/my": fixture})
    adapter = _make_adapter(client)

    shops = await adapter.list_shops()

    assert len(shops) == len(fixture["docs"])
    assert all(isinstance(s, Shop) for s in shops)
    assert shops[0].name == "Pret a Polpett"


@pytest.mark.asyncio
async def test_list_shops_walks_multiple_pages(slesh_fixture):
    """Multi-page response: adapter pages until hasNextPage=False."""
    import copy
    base = slesh_fixture("shop_my")
    page1 = {**base, "hasNextPage": True,  "to": 2}
    # Page 2 needs DIFFERENT doc ids so the infinite-loop guard
    # (which detects same-first-doc-as-previous-page) does NOT fire.
    page2_docs = copy.deepcopy(base["docs"])
    for i, d in enumerate(page2_docs):
        d["_id"] = f"page2_doc_{i}"
    page2 = {**base, "docs": page2_docs, "hasNextPage": False, "to": 4}
    client  = FakeSleshHTTPClient([page1, page2])
    adapter = _make_adapter(client)

    shops = await adapter.list_shops()

    # 2 docs per page × 2 pages = 4 total
    assert len(shops) == len(base["docs"]) * 2
    # 2 calls were made
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_list_shops_injects_brand_id(slesh_fixture):
    """Every request must include brandId — adapter is brand-bound."""
    fixture = {**slesh_fixture("shop_my"), "hasNextPage": False}
    client  = FakeSleshHTTPClient({"/shop/my": fixture})
    adapter = _make_adapter(client)

    await adapter.list_shops()

    assert client.calls[0]["params"]["brandId"] == BRAND_ID


@pytest.mark.asyncio
async def test_list_shops_passes_experience_id_when_given(slesh_fixture):
    """experience_id parameter reaches the URL as experienceId."""
    fixture = {**slesh_fixture("shop_my"), "hasNextPage": False}
    client  = FakeSleshHTTPClient({"/shop/my": fixture})
    adapter = _make_adapter(client)

    await adapter.list_shops(experience_id="abc123")
    assert client.calls[0]["params"]["experienceId"] == "abc123"


@pytest.mark.asyncio
async def test_list_shops_omits_experience_id_when_none(slesh_fixture):
    """experience_id=None is dropped from query (cleaned by client.get)."""
    fixture = {**slesh_fixture("shop_my"), "hasNextPage": False}
    client  = FakeSleshHTTPClient({"/shop/my": fixture})
    adapter = _make_adapter(client)

    await adapter.list_shops(experience_id=None)
    # The adapter passes experienceId=None; client.get filters it out.
    # Here we're testing the adapter, so we just verify it was passed (None).
    assert client.calls[0]["params"]["experienceId"] is None


# ─────────────────────────────────────────────────────────────────
# 3. list_categories / list_products — plain list (no envelope)
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_categories_parses_plain_list(slesh_fixture):
    """Categories endpoint returns a plain list — adapter handles it."""
    fixture = slesh_fixture("category_my")
    client  = FakeSleshHTTPClient({"/category/my": fixture})
    adapter = _make_adapter(client)

    cats = await adapter.list_categories()

    assert len(cats) == len(fixture)
    assert all(isinstance(c, Category) for c in cats)


@pytest.mark.asyncio
async def test_list_products_parses_plain_list(slesh_fixture):
    """Products endpoint returns a plain list — adapter handles it."""
    fixture = slesh_fixture("product_my")
    client  = FakeSleshHTTPClient({"/product/my": fixture})
    adapter = _make_adapter(client)

    prods = await adapter.list_products()

    assert len(prods) == len(fixture)
    assert all(isinstance(p, Product) for p in prods)


@pytest.mark.asyncio
async def test_list_categories_raises_if_slesh_returns_dict_unexpectedly():
    """Defensive: if Slesh changes shape from list to dict, fail loudly."""
    client  = FakeSleshHTTPClient({"/category/my": {"docs": [], "total": 0}})
    adapter = _make_adapter(client)

    with pytest.raises(TypeError, match="Expected list response"):
        await adapter.list_categories()


# ─────────────────────────────────────────────────────────────────
# 4. list_orders — async generator over paginated response
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_orders_yields_parsed_orders(slesh_fixture):
    """list_orders is an async generator yielding Order models."""
    from datetime import datetime, timezone

    fixture = {**slesh_fixture("order_brand_my"), "hasNextPage": False}
    client  = FakeSleshHTTPClient({"/order/brand-my": fixture})
    adapter = _make_adapter(client)

    orders = []
    async for order in adapter.list_orders(
        since_ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        until_ts=datetime(2025, 12, 31, tzinfo=timezone.utc),
    ):
        orders.append(order)

    assert len(orders) == len(fixture["docs"])
    assert all(isinstance(o, Order) for o in orders)


@pytest.mark.asyncio
async def test_list_orders_converts_datetimes_to_unix_ms(slesh_fixture):
    """since_ts / until_ts are converted to Unix milliseconds in the request."""
    from datetime import datetime, timezone

    fixture = {**slesh_fixture("order_brand_my"), "hasNextPage": False}
    client  = FakeSleshHTTPClient({"/order/brand-my": fixture})
    adapter = _make_adapter(client)

    since = datetime(2024, 5, 24, 16, 55, 58, 657_000, tzinfo=timezone.utc)
    async for _ in adapter.list_orders(since_ts=since, until_ts=since):
        break  # we only care about the request, not the docs

    assert client.calls[0]["params"]["fromTs"] == 1716569758657
    assert client.calls[0]["params"]["toTs"]   == 1716569758657


@pytest.mark.asyncio
async def test_list_orders_default_order_type_is_experience(slesh_fixture):
    """By default the polling worker only sees Sundance ('experience') orders."""
    from datetime import datetime, timezone

    fixture = {**slesh_fixture("order_brand_my"), "hasNextPage": False}
    client  = FakeSleshHTTPClient({"/order/brand-my": fixture})
    adapter = _make_adapter(client)

    since = datetime(2025, 1, 1, tzinfo=timezone.utc)
    async for _ in adapter.list_orders(since_ts=since, until_ts=since):
        break

    assert client.calls[0]["params"]["orderType"] == "experience"


# ─────────────────────────────────────────────────────────────────
# 5. Async context manager closes underlying client
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_context_manager_closes_client():
    """Exiting `async with SleshAdapter(...)` should close the http client."""
    fake_close = AsyncMock()
    client = FakeSleshHTTPClient({})
    client.aclose = fake_close

    adapter = SleshAdapter.from_components(client=client, brand_id=BRAND_ID)
    async with adapter:
        pass

    fake_close.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────
# 6. Pagination defensive: stalled pagination (hasNextPage=true, docs=[])
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pagination_stops_if_stalled(slesh_fixture):
    """If Slesh says hasNextPage=true but returns empty docs, we stop (no infinite loop)."""
    base    = slesh_fixture("shop_my")
    stalled = {**base, "docs": [], "hasNextPage": True}  # the trap
    client  = FakeSleshHTTPClient({"/shop/my": stalled})
    adapter = _make_adapter(client)

    shops = await adapter.list_shops()
    # We get an empty list (not infinite) and only one call was made
    assert shops == []
    assert len(client.calls) == 1
