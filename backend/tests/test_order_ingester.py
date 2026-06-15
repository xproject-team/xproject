"""Unit tests for order_ingester — cart line ingestion + skip rules.

Tests use lightweight fakes so we never touch the DB:
- FakeService.ingest_sale records the SaleIngestRequest it would persist
- FakeBar / FakeProduct mimic just the attributes ingest_order reads

These tests prove:
- Orders without a shop reference are skipped wholesale
- Refunded cart lines are skipped (one per line)
- Food lines are ingested (revenue-only); Supply/ingredient lines skipped
- Missing bar / product references skip without crashing
- Idempotency replays count correctly
- payment_type maps Slesh\'s vocabulary correctly (incl. tap-to-pay rename)
- Unknown payment.type values become None + warn once

Spec: docs/slesh-integration-roadmap.md \u00a7B6.3 + \u00a7B8b.4.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from unittest.mock import AsyncMock

from app.modules.pos.order_ingester import (
    IngestResult,
    _LookupCache,
    _map_payment_type,
    ingest_order,
)
from app.modules.products.models import ProductType
from app.modules.stock_transactions.models import PaymentType


# ─── Lightweight fakes (no DB) ──────────────────────────────────────────

@dataclass
class FakeBar:
    id:          UUID
    name:        str
    event_id:    UUID
    slesh_negozio_id: str
    auto_created: bool = False


@dataclass
class FakeProduct:
    id:               UUID
    name:             str
    product_type:     ProductType
    external_pos_id:  str
    is_archived:      bool = False


@dataclass
class FakeShopRef:
    id:    str
    name:  str | None = None


@dataclass
class FakePayment:
    type: str | None
    status: str | None = None


@dataclass
class FakeCartLine:
    id:           str
    product:      str             # external product id
    gross_amount: int = 1000      # cents
    status:       str | None = "completed"
    product_name: dict | str | None = None


@dataclass
class FakeOrder:
    id:        str
    cart:      list[FakeCartLine]
    shop:      FakeShopRef | str | None
    payment:   FakePayment | None = None
    type:      str = "experience"
    status:    str = "completed"


@dataclass
class FakeIngestSaleResult:
    """Mimics StockTransactionService.IngestResult shape."""
    parent: object = None
    children: list = field(default_factory=list)
    idempotency_replay: bool = False


class FakeService:
    """Records every ingest_sale / ingest_food_sale call for assertions."""
    def __init__(self, *, replay: bool = False) -> None:
        self.calls: list[Any] = []        # every request, any path
        self.drink_calls: list[Any] = []  # routed through ingest_sale
        self.food_calls: list[Any] = []   # routed through ingest_food_sale
        self.replay = replay

    async def ingest_sale(self, *, tenant_id: UUID, data) -> FakeIngestSaleResult:
        self.calls.append(data)
        self.drink_calls.append(data)
        return FakeIngestSaleResult(idempotency_replay=self.replay)

    async def ingest_food_sale(self, *, tenant_id: UUID, data) -> FakeIngestSaleResult:
        self.calls.append(data)
        self.food_calls.append(data)
        return FakeIngestSaleResult(idempotency_replay=self.replay)


# Patch the lookup helpers used by ingest_order so they hit our fakes.
@pytest.fixture
def patched_lookups(monkeypatch):
    """Returns (registered_bars_dict, registered_products_dict).

    Monkeypatches _resolve_bar and _find_product_by_external_id in the
    order_ingester module. The _resolve_bar fake mirrors the real
    auto-create behaviour: unknown slesh_ids cause a fresh FakeBar with
    auto_created=True to be added to the bars dict and returned, so
    tests can both pre-register bars AND assert on the auto-create
    branch via the same dict.
    """
    bars: dict[str, FakeBar] = {}
    products: dict[str, FakeProduct] = {}

    async def _fake_resolve_bar(db, tenant_id, event_id, slesh_id):
        existing = bars.get(slesh_id)
        if existing is not None:
            return existing
        display = (
            f"{slesh_id[:8]}…{slesh_id[-4:]}"
            if len(slesh_id) > 12 else slesh_id
        )
        new_bar = FakeBar(
            id=uuid4(),
            name=display,
            event_id=event_id,
            slesh_negozio_id=slesh_id,
            auto_created=True,
        )
        bars[slesh_id] = new_bar
        return new_bar

    async def _fake_find_product(db, tenant_id, external_id):
        return products.get(external_id)

    import app.modules.pos.order_ingester as oi
    monkeypatch.setattr(oi, "_resolve_bar", _fake_resolve_bar)
    monkeypatch.setattr(oi, "_find_product_by_external_id", _fake_find_product)

    return bars, products


TENANT_ID = UUID("25ef916c-a288-44ae-b17c-8dfd09390834")
EVENT_ID  = UUID("4e9f9699-b372-4649-9d16-9634898bb08d")


def _make_drink_product(ext_id: str) -> FakeProduct:
    return FakeProduct(
        id               = uuid4(),
        name             = "Cocktail",
        product_type     = ProductType.DRINK,
        external_pos_id  = ext_id,
    )


def _make_food_product(ext_id: str) -> FakeProduct:
    return FakeProduct(
        id               = uuid4(),
        name             = "Burger",
        product_type     = ProductType.FOOD,
        external_pos_id  = ext_id,
    )


def _make_supply_product(ext_id: str) -> FakeProduct:
    return FakeProduct(
        id               = uuid4(),
        name             = "Cups",
        product_type     = ProductType.SUPPLY,
        external_pos_id  = ext_id,
    )


def _make_bar(slesh_id: str) -> FakeBar:
    return FakeBar(
        id               = uuid4(),
        name             = "Cocktail Bar",
        event_id         = EVENT_ID,
        slesh_negozio_id = slesh_id,
    )


# ─── _map_payment_type ────────────────────────────────────────────────

def test_map_payment_type_known_values():
    assert _map_payment_type("token")      == PaymentType.TOKEN
    assert _map_payment_type("stripe")     == PaymentType.STRIPE
    assert _map_payment_type("cash")       == PaymentType.CASH
    assert _map_payment_type("card")       == PaymentType.CARD
    assert _map_payment_type("adyen")      == PaymentType.ADYEN
    assert _map_payment_type("mixed")      == PaymentType.MIXED


def test_map_payment_type_tap_to_pay_rename():
    """Slesh sends 'tap-to-pay' (hyphen); we store 'tap_to_pay'."""
    assert _map_payment_type("tap-to-pay") == PaymentType.TAP_TO_PAY
    assert _map_payment_type("tap_to_pay") == PaymentType.TAP_TO_PAY


def test_map_payment_type_case_insensitive():
    assert _map_payment_type("TOKEN") == PaymentType.TOKEN
    assert _map_payment_type("Cash")  == PaymentType.CASH


def test_map_payment_type_strips_whitespace():
    assert _map_payment_type("  token  ") == PaymentType.TOKEN


def test_map_payment_type_none_returns_none():
    assert _map_payment_type(None) is None


def test_map_payment_type_unknown_logs_once(caplog):
    """First unknown value warns; second of same value does NOT (dedup)."""
    caplog.set_level(logging.WARNING)
    # Use a unique value to avoid pollution from other tests
    _map_payment_type("crypto-payment-future-thing")
    _map_payment_type("crypto-payment-future-thing")  # second call

    matches = [r for r in caplog.records if "crypto-payment" in r.getMessage()]
    assert len(matches) == 1, f"expected exactly 1 warning, got {len(matches)}"


# ─── ingest_order — happy path ────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_order_one_drink_line(patched_lookups):
    bars, products = patched_lookups
    bars["shop_1"]      = _make_bar("shop_1")
    products["prod_1"]  = _make_drink_product("prod_1")

    order = FakeOrder(
        id    = "ord_1",
        shop  = FakeShopRef(id="shop_1", name="Cocktail Bar"),
        cart  = [FakeCartLine(id="line_1", product="prod_1")],
        payment = FakePayment(type="token"),
    )
    service = FakeService()

    result = await ingest_order(
        db=None, order=order, event_id=EVENT_ID, tenant_id=TENANT_ID,
        service=service,
    )

    assert result.lines_total      == 1
    assert result.lines_ingested   == 1
    assert result.lines_skipped    == 0
    assert result.lines_errors     == 0
    assert len(service.calls)      == 1
    sent = service.calls[0]
    assert sent.payment_type       == PaymentType.TOKEN
    assert sent.qty                == Decimal("1")
    assert sent.price_cents        == 1000


# ─── ingest_order — skip rules ────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_order_no_shop_skips_whole_order(patched_lookups):
    bars, products = patched_lookups
    order = FakeOrder(
        id    = "ord_1",
        shop  = None,
        cart  = [FakeCartLine(id="line_1", product="prod_1")],
    )
    service = FakeService()

    result = await ingest_order(
        db=None, order=order, event_id=EVENT_ID, tenant_id=TENANT_ID,
        service=service,
    )

    assert result.lines_skipped == 1
    assert result.lines_ingested == 0
    assert "no embedded shop" in (result.skip_reasons[0] if result.skip_reasons else "")
    assert service.calls == []


@pytest.mark.asyncio
async def test_ingest_order_unmatched_bar_auto_creates(patched_lookups):
    """Unknown shop_id -> ingester auto-creates a stub bar; sale still
    lands. The no-data-loss invariant: every Slesh sale attributes to
    some bar so revenue is never silently dropped."""
    bars, products = patched_lookups
    products["prod_1"] = _make_drink_product("prod_1")
    # No bar pre-registered with slesh_id "shop_1"

    order = FakeOrder(
        id      = "ord_1",
        shop    = FakeShopRef(id="shop_1"),
        cart    = [FakeCartLine(id="line_1", product="prod_1")],
        payment = FakePayment(type="card"),
    )
    service = FakeService()

    result = await ingest_order(
        db=None, order=order, event_id=EVENT_ID, tenant_id=TENANT_ID,
        service=service,
    )

    assert result.lines_skipped  == 0
    assert result.lines_ingested == 1
    assert result.lines_errors   == 0
    assert "shop_1" in bars
    new_bar = bars["shop_1"]
    assert new_bar.slesh_negozio_id == "shop_1"
    assert new_bar.auto_created is True
    assert len(service.calls) == 1
    assert service.calls[0].bar_id == new_bar.id


@pytest.mark.asyncio
async def test_ingest_order_refunded_line_skips(patched_lookups):
    bars, products = patched_lookups
    bars["shop_1"]      = _make_bar("shop_1")
    products["prod_1"]  = _make_drink_product("prod_1")

    order = FakeOrder(
        id    = "ord_1",
        shop  = FakeShopRef(id="shop_1"),
        cart  = [FakeCartLine(id="line_1", product="prod_1", status="refunded")],
    )
    service = FakeService()
    db_mock = AsyncMock()

    result = await ingest_order(
        db=db_mock, order=order, event_id=EVENT_ID, tenant_id=TENANT_ID,
        service=service,
    )

    assert result.lines_skipped == 1
    assert result.lines_ingested == 0
    assert any("refunded" in r for r in result.skip_reasons)
    assert service.calls == []
    # Verify the pos_line_status='refunded' UPDATE was issued exactly once
    assert db_mock.execute.await_count == 1


@pytest.mark.asyncio
async def test_ingest_order_food_line_ingested(patched_lookups):
    """Food lines now reach the dashboard via ingest_food_sale (revenue-only)."""
    bars, products = patched_lookups
    bars["shop_1"]      = _make_bar("shop_1")
    products["prod_1"]  = _make_food_product("prod_1")

    order = FakeOrder(
        id    = "ord_1",
        shop  = FakeShopRef(id="shop_1"),
        cart  = [FakeCartLine(id="line_1", product="prod_1", gross_amount=1500)],
        payment = FakePayment(type="card"),
    )
    service = FakeService()

    result = await ingest_order(
        db=None, order=order, event_id=EVENT_ID, tenant_id=TENANT_ID,
        service=service,
    )

    assert result.lines_ingested == 1
    assert result.lines_skipped  == 0
    assert result.lines_errors   == 0
    # routed to the FOOD path, not the drink/recipe path
    assert len(service.food_calls)  == 1
    assert len(service.drink_calls) == 0
    sent = service.food_calls[0]
    assert sent.event_id     == EVENT_ID
    assert sent.bar_id       == bars["shop_1"].id
    assert sent.product_id   == products["prod_1"].id
    assert sent.qty          == Decimal("1")
    assert sent.price_cents  == 1500
    assert sent.payment_type == PaymentType.CARD
    assert sent.source_idempotency_key == "slesh:ord_1:line_1"


@pytest.mark.asyncio
async def test_ingest_order_food_line_replay_counted(patched_lookups):
    """A replayed food line counts as a replay, not a fresh ingest."""
    bars, products = patched_lookups
    bars["shop_1"]      = _make_bar("shop_1")
    products["prod_1"]  = _make_food_product("prod_1")

    order = FakeOrder(
        id    = "ord_1",
        shop  = FakeShopRef(id="shop_1"),
        cart  = [FakeCartLine(id="line_1", product="prod_1")],
        payment = FakePayment(type="card"),
    )
    service = FakeService(replay=True)

    result = await ingest_order(
        db=None, order=order, event_id=EVENT_ID, tenant_id=TENANT_ID,
        service=service,
    )

    assert result.lines_replayed == 1
    assert result.lines_ingested == 0
    assert len(service.food_calls) == 1


@pytest.mark.asyncio
async def test_ingest_order_supply_line_skips(patched_lookups):
    """Non drink/food lines (supply/ingredient) are still skipped."""
    bars, products = patched_lookups
    bars["shop_1"]      = _make_bar("shop_1")
    products["prod_1"]  = _make_supply_product("prod_1")

    order = FakeOrder(
        id    = "ord_1",
        shop  = FakeShopRef(id="shop_1"),
        cart  = [FakeCartLine(id="line_1", product="prod_1")],
    )
    service = FakeService()

    result = await ingest_order(
        db=None, order=order, event_id=EVENT_ID, tenant_id=TENANT_ID,
        service=service,
    )

    assert result.lines_skipped  == 1
    assert result.lines_ingested == 0
    assert any("not drink/food" in r for r in result.skip_reasons)
    assert service.calls == []


@pytest.mark.asyncio
async def test_ingest_order_unmatched_product_skips(patched_lookups):
    bars, products = patched_lookups
    bars["shop_1"] = _make_bar("shop_1")
    # No product registered with id "prod_unknown"

    order = FakeOrder(
        id    = "ord_1",
        shop  = FakeShopRef(id="shop_1"),
        cart  = [FakeCartLine(id="line_1", product="prod_unknown")],
    )
    service = FakeService()

    result = await ingest_order(
        db=None, order=order, event_id=EVENT_ID, tenant_id=TENANT_ID,
        service=service,
    )

    assert result.lines_skipped == 1
    assert any("no product matched" in r for r in result.skip_reasons)


# ─── ingest_order — idempotency ───────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_order_replay_counted_separately(patched_lookups):
    bars, products = patched_lookups
    bars["shop_1"]      = _make_bar("shop_1")
    products["prod_1"]  = _make_drink_product("prod_1")

    order = FakeOrder(
        id    = "ord_1",
        shop  = FakeShopRef(id="shop_1"),
        cart  = [FakeCartLine(id="line_1", product="prod_1")],
        payment = FakePayment(type="token"),
    )
    service = FakeService(replay=True)   # service reports replay

    result = await ingest_order(
        db=None, order=order, event_id=EVENT_ID, tenant_id=TENANT_ID,
        service=service,
    )

    assert result.lines_replayed == 1
    assert result.lines_ingested == 0
    assert len(service.calls) == 1


# ─── ingest_order — idempotency key + payment_type wiring ─────────────

@pytest.mark.asyncio
async def test_ingest_order_idempotency_key_format(patched_lookups):
    """idempotency key = slesh:<order_id>:<line_id>"""
    bars, products = patched_lookups
    bars["shop_1"]      = _make_bar("shop_1")
    products["prod_1"]  = _make_drink_product("prod_1")

    order = FakeOrder(
        id    = "688fbd64",
        shop  = FakeShopRef(id="shop_1"),
        cart  = [FakeCartLine(id="line_abc", product="prod_1")],
        payment = FakePayment(type="token"),
    )
    service = FakeService()

    await ingest_order(
        db=None, order=order, event_id=EVENT_ID, tenant_id=TENANT_ID,
        service=service,
    )

    assert service.calls[0].source_idempotency_key == "slesh:688fbd64:line_abc"


@pytest.mark.asyncio
async def test_ingest_order_payment_type_propagated(patched_lookups):
    """All cart lines in one order share the order\'s payment.type."""
    bars, products = patched_lookups
    bars["shop_1"]       = _make_bar("shop_1")
    products["prod_1"]   = _make_drink_product("prod_1")
    products["prod_2"]   = _make_drink_product("prod_2")

    order = FakeOrder(
        id    = "ord_1",
        shop  = FakeShopRef(id="shop_1"),
        cart  = [
            FakeCartLine(id="line_1", product="prod_1"),
            FakeCartLine(id="line_2", product="prod_2"),
        ],
        payment = FakePayment(type="card"),
    )
    service = FakeService()

    await ingest_order(
        db=None, order=order, event_id=EVENT_ID, tenant_id=TENANT_ID,
        service=service,
    )

    assert len(service.calls) == 2
    assert all(c.payment_type == PaymentType.CARD for c in service.calls)


@pytest.mark.asyncio
async def test_ingest_order_payment_type_none_when_no_payment(patched_lookups):
    bars, products = patched_lookups
    bars["shop_1"]      = _make_bar("shop_1")
    products["prod_1"]  = _make_drink_product("prod_1")

    order = FakeOrder(
        id    = "ord_1",
        shop  = FakeShopRef(id="shop_1"),
        cart  = [FakeCartLine(id="line_1", product="prod_1")],
        payment = None,
    )
    service = FakeService()

    await ingest_order(
        db=None, order=order, event_id=EVENT_ID, tenant_id=TENANT_ID,
        service=service,
    )

    assert service.calls[0].payment_type is None


# ─── ingest_order — cache reuse ───────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_order_uses_supplied_cache(patched_lookups):
    """Cache passed in is mutated; bar + product are remembered."""
    bars, products = patched_lookups
    bars["shop_1"]      = _make_bar("shop_1")
    products["prod_1"]  = _make_drink_product("prod_1")

    order = FakeOrder(
        id    = "ord_1",
        shop  = FakeShopRef(id="shop_1"),
        cart  = [FakeCartLine(id="line_1", product="prod_1")],
        payment = FakePayment(type="token"),
    )
    cache = _LookupCache()
    service = FakeService()

    await ingest_order(
        db=None, order=order, event_id=EVENT_ID, tenant_id=TENANT_ID,
        service=service, cache=cache,
    )

    assert "shop_1" in cache.bars
    assert "prod_1" in cache.products
