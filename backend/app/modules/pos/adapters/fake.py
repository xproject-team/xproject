"""Fake POS adapter — provider-shaped payloads from generated data.

Substitutes for the real adapter behind BasePOSAdapter in staging
(POS_ADAPTER=fake). Yields the SAME parsed pydantic models as the real
adapter, produced by running raw dicts in the provider's exact wire
shape (aliases and all) through the real schemas — so schema parsing,
the ingester, the event_orders upsert, parking, and everything derived
all execute production code. What it skips is transport only: HTTP,
pagination, retry, rate limiting, circuit breaking.

DATA CONTRACT — mirrors what was verified on production (2026-08):
  - subtotal = fiscal_gross + deposit on EVERY order, no exceptions
    (held on 15,387/15,387 production rows)
  - VAT computed on the deposit-INCLUSIVE subtotal (10% Italian rate,
    VAT-in): net + vat == subtotal, which differs from fiscal gross
    whenever a deposit exists
  - order types: "experience" (payment token) and "cash-desk" (payment
    mixed, no token, exact multiples of 1000 cents — €10/head door
    admission at the service shop, whose "Ingresso" product is
    deliberately NOT in the catalog so those orders produce event_orders
    rows with zero stock lines, as on production)
  - deposit products: Bicchiere 100c, Cauzione Bottiglia 200c; deposit
    RETURNS appear as refunded lines inside otherwise-confirmed orders
    (production's 422 refunded lines were exactly these)
  - a fully refunded order arrives with all lines refunded and every
    order-level amount at 0
  - ~2% of orders reference GHOST_SHOP_ID, which list_shops never
    returns — no bar can ever be mapped, exercising
    pending_shop_mappings parking
  - scale: 3000–4500 orders per 16:00–02:00 event, whole-euro prices,
    average order ~12 EUR, peak hour 18:00 local

DETERMINISM: the stream is a pure function of the time window. Orders
are generated per wall-clock minute from a seeded RNG, so overlapping
poll windows (the real poller's 60s overlap) re-serve byte-identical
orders and replay through the real idempotency path, exactly like the
provider re-serving the same rows.

HARD RULE: this module must never import app.core.config or httpx — it
is constructed with nothing, so no Slesh credential or URL can leak in
(see factory.get_pos_adapter and the safety tests).
"""
from __future__ import annotations

import hashlib
import random
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

from app.modules.pos.adapters.base import BasePOSAdapter
from app.modules.pos.schemas import Brand, Category, Order, Product, Shop

# The one brand the fake answers for. Value mirrored (not imported) from
# factory.FAKE_BRAND_ID — importing factory here would drag settings in.
FAKE_BRAND_ID = "fakebrand000000000000fa9e"

# Fixed +2 offset (CEST) instead of zoneinfo("Europe/Rome"): the season
# runs in summer and the slim container image may lack the tz database —
# a hard dependency for a fake is not worth the fidelity of one DST hour.
LOCAL_TZ = timezone(timedelta(hours=2))

# Shop that appears on orders but never in list_shops — unmappable by
# construction, so its orders always park in pending_shop_mappings.
GHOST_SHOP_ID = "fake500000000000000009ff"

# ─── Catalog (raw wire shapes, exported for staging seeding) ─────────────────

FAKE_SHOPS_RAW: list[dict] = [
    {"_id": "fake500000000000000000b1", "name": "Bar Centrale", "isEnabled": True},
    {"_id": "fake500000000000000000b2", "name": "Bar Palco",    "isEnabled": True},
    {"_id": "fake500000000000000000f1", "name": "Food Truck",   "isEnabled": True},
    {"_id": "fake500000000000000000a1", "name": "Accrediti",    "isEnabled": True},
]

_DRINKS: list[tuple[str, str, int]] = [
    ("fakeb0000000000000000d01", "Spritz",          800),
    ("fakeb0000000000000000d02", "Gin Tonic",       900),
    ("fakeb0000000000000000d03", "Mojito",         1000),
    ("fakeb0000000000000000d04", "Birra Media",     600),
    ("fakeb0000000000000000d05", "Vino Bianco",     500),
    ("fakeb0000000000000000d06", "Vino Rosso",      500),
    ("fakeb0000000000000000d07", "Rum Cola",        900),
    ("fakeb0000000000000000d08", "Acqua",           200),
    ("fakeb0000000000000000d09", "Cocktail Premium", 1200),
    ("fakeb0000000000000000d10", "Analcolico",      700),
]
_FOOD: list[tuple[str, str, int]] = [
    ("fakeb0000000000000000f01", "Panino",   700),
    ("fakeb0000000000000000f02", "Arancina", 400),
]
_DEPOSITS: list[tuple[str, str, int]] = [
    ("fakeb0000000000000000c01", "Bicchiere",          100),
    ("fakeb0000000000000000c02", "Cauzione Bottiglia", 200),
]
# Door admission — deliberately NOT part of list_products (see docstring).
_INGRESSO_ID = "fakeb0000000000000000e01"

# Product/Category names are localized dicts on the wire ({"it": ...}).
FAKE_PRODUCTS_RAW: list[dict] = [
    {"_id": pid, "name": {"it": name}, "_type": "physical",
     "defaultPrice": price, "isEnabled": True}
    for pid, name, price in (*_DRINKS, *_FOOD, *_DEPOSITS)
]

FAKE_CATEGORIES_RAW: list[dict] = [
    {"_id": "fakec0000000000000000001", "name": {"it": "Drinks"},   "isEnabled": True},
    {"_id": "fakec0000000000000000002", "name": {"it": "Food"},     "isEnabled": True},
    {"_id": "fakec0000000000000000003", "name": {"it": "Cauzioni"}, "isEnabled": True},
]

_BAR_SHOPS = ["fake500000000000000000b1", "fake500000000000000000b2"]
_FOOD_SHOP = "fake500000000000000000f1"
_CASH_DESK_SHOP = "fake500000000000000000a1"
_SHOP_NAMES = {s["_id"]: s["name"] for s in FAKE_SHOPS_RAW}
_SHOP_NAMES[GHOST_SHOP_ID] = "Chiringuito"  # came online mid-event, never mapped

# Orders per minute by LOCAL hour — sums to ~3,780 over a 16:00–02:00
# event (within the 3,000–4,500 production band); peak at 18:00.
_HOUR_RATES = {16: 4, 17: 7, 18: 11, 19: 9, 20: 8, 21: 7, 22: 6, 23: 5, 0: 4, 1: 2}

# ~1,500 distinct wristband customers per event, like production's
# identified-guest pool.
_CUSTOMER_POOL = 1500


def _hex24(*parts: object) -> str:
    return hashlib.sha1(":".join(str(p) for p in parts).encode()).hexdigest()[:24]


def _vat_split(subtotal_cents: int) -> tuple[float, float]:
    """(vat, net) at the Italian 10% VAT-inclusive rate, computed on the
    deposit-INCLUSIVE subtotal — unrounded floats, as the provider sends
    them (net=909.0909… for a €10 line)."""
    vat = subtotal_cents * 10.0 / 110.0
    return vat, subtotal_cents - vat


def _make_order_raw(minute_start_ms: int, index: int, rng: random.Random) -> dict:
    order_id = _hex24("order", minute_start_ms, index)
    created_at = minute_start_ms + rng.randrange(0, 60_000)

    is_cash_desk = rng.random() < 0.012
    fully_refunded = (not is_cash_desk) and rng.random() < 0.01

    lines: list[dict] = []

    def _line(product_id: str, name: str, gross: int, status: str) -> dict:
        return {
            "_id": _hex24("line", order_id, len(lines)),
            "_product": product_id,
            "_productName": {"it": name},
            "_grossAmount": gross,
            "status": status,
        }

    if is_cash_desk:
        heads = rng.choices([1, 2, 3], weights=[80, 15, 5])[0]
        lines.append(_line(_INGRESSO_ID, "Ingresso", heads * 1000, "confirmed"))
        shop_id = _CASH_DESK_SHOP
    else:
        shop_id = rng.choices(
            [*_BAR_SHOPS, _FOOD_SHOP, GHOST_SHOP_ID], weights=[40, 35, 23, 2],
        )[0]
        pool = _FOOD if shop_id == _FOOD_SHOP else _DRINKS
        line_status = "refunded" if fully_refunded else "confirmed"
        for _ in range(rng.choices([1, 2, 3], weights=[50, 35, 15])[0]):
            pid, name, price = rng.choice(pool)
            lines.append(_line(pid, name, price, line_status))
        # Deposit taken with the drinks (confirmed, counts toward subtotal).
        if not fully_refunded and shop_id != _FOOD_SHOP:
            if rng.random() < 0.30:
                lines.append(_line(*_DEPOSITS[0], "confirmed"))
            elif rng.random() < 0.05:
                lines.append(_line(*_DEPOSITS[1], "confirmed"))
        # Deposit RETURN — a refunded line inside a confirmed order
        # (production's only refunded-line population).
        if not fully_refunded and rng.random() < 0.08:
            pid, name, price = _DEPOSITS[0] if rng.random() < 0.85 else _DEPOSITS[1]
            lines.append(_line(pid, name, price, "refunded"))

    confirmed = [ln for ln in lines if ln["status"] == "confirmed"]
    subtotal = sum(ln["_grossAmount"] for ln in confirmed)
    deposit = sum(
        ln["_grossAmount"] for ln in confirmed
        if ln["_product"] in (_DEPOSITS[0][0], _DEPOSITS[1][0])
    )
    fiscal_gross = subtotal - deposit
    vat, net = _vat_split(subtotal)

    raw: dict = {
        "_id": order_id,
        "_type": "cash-desk" if is_cash_desk else "experience",
        "_createdAt": created_at,
        "status": "refunded" if fully_refunded else "confirmed",
        "_shop": {"_id": shop_id, "name": _SHOP_NAMES[shop_id]},
        "cart": lines,
        "__cartGrossAmount": subtotal,
        "__cartVatAmount": vat,
        "__cartDepositAmount": deposit,
        "__cartFiscalGrossAmount": fiscal_gross,
        "__cartFiscalNetAmount": net,
        "__cartDiscountAmount": 0,
        "__subtotal": subtotal,
    }

    if is_cash_desk:
        raw["payment"] = {"_type": "mixed"}
    else:
        customer_n = rng.randrange(_CUSTOMER_POOL)
        band = _hex24("band", customer_n)
        raw["payment"] = {"_type": "token", "_paymentToken": band}
        # user/operator are BARE MONGO ID STRINGS, not populated objects:
        # the real adapter's list_orders sends no populatedField param,
        # so that is what the provider returns on the path production
        # runs — and it is load-bearing. The ingester's _as_extras_blob
        # wraps a string as {'_id': value} but dumps a populated model
        # BY FIELD NAME ({'id': ...}), and the customer-features builder
        # consumes raw_extras->'user'->>'_id' (verified on production,
        # 22 Aug). Emitting populated objects here made staging's
        # post-event close create 0 sessions from 8,084 orders.
        if rng.random() < 0.80:
            raw["user"] = _hex24("cust", customer_n)
            if rng.random() < 0.60:
                raw["_customerEmail"] = f"guest{customer_n}@staging.example"
        raw["operator"] = _hex24("operator", shop_id)

    return raw


class FakePOSAdapter(BasePOSAdapter):
    """Read-only fake fulfilling the BasePOSAdapter contract.

    Constructor takes no configuration on purpose — passing anything is
    a TypeError, so no credential or URL can arrive by any parameter.
    """

    def __init__(self) -> None:
        pass

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
        return [Shop.model_validate(s) for s in FAKE_SHOPS_RAW]

    async def list_categories(self, experience_id: str | None = None) -> list[Category]:
        return [Category.model_validate(c) for c in FAKE_CATEGORIES_RAW]

    async def list_products(
        self,
        experience_id: str | None = None,
        *,
        populated_field: str | None = None,
    ) -> list[Product]:
        return [Product.model_validate(p) for p in FAKE_PRODUCTS_RAW]

    async def list_orders(
        self,
        since_ts: datetime,
        until_ts: datetime,
        *,
        experience_id: str | None = None,
        shop_id: str | None = None,
        order_type: str | None = "experience",
    ) -> AsyncIterator[Order]:
        """Stream deterministic orders in [since_ts, until_ts), ascending
        by created_at — the same contract as the real adapter's
        sortDir=asc stream. Filters mirror the provider's query params;
        experience_id is accepted and ignored (one fake experience)."""
        since_ms = int(since_ts.timestamp() * 1000)
        until_ms = int(until_ts.timestamp() * 1000)

        minute = (since_ms // 60_000) * 60_000
        while minute < until_ms:
            local_hour = datetime.fromtimestamp(minute / 1000, tz=LOCAL_TZ).hour
            rate = _HOUR_RATES.get(local_hour, 0)
            if rate:
                rng = random.Random(f"fakepos:{FAKE_BRAND_ID}:{minute}")
                count = max(0, rate + rng.choice((-1, 0, 0, 1)))
                minute_orders = [
                    _make_order_raw(minute, i, rng) for i in range(count)
                ]
                minute_orders.sort(key=lambda r: r["_createdAt"])
                for raw in minute_orders:
                    if not (since_ms <= raw["_createdAt"] < until_ms):
                        continue
                    if order_type is not None and raw["_type"] != order_type:
                        continue
                    if shop_id is not None and raw["_shop"]["_id"] != shop_id:
                        continue
                    yield Order.model_validate(raw)
            minute += 60_000
