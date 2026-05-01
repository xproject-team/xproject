"""Pydantic schema tests — Layer 2 sandbox-defense regression suite.

These tests use the recorded fixtures in tests/fixtures/slesh/ as their
input data. Every test is:

  - DETERMINISTIC — same fixture input every run
  - FAST — no network calls, no DB
  - REAL — fixtures are real (redacted) Slesh production responses

WHY THIS FILE EXISTS:
The Slesh schemas have to handle three real-world surprises that we only
discovered by recording fixtures (not from the OpenAPI spec):

  1. _netAmount and _vatAmount are FLOATS, not ints (VAT splits)
  2. user/operator can be a populated dict OR a bare string id
  3. shop is sometimes absent from an order entirely
  4. Slesh adds new fields without notice (e.g. `cleanWalletsOnExperienceEnded`
     showed up overnight between Apr 29 and May 1)

If any of those regress, these tests fail loudly. They are the cheapest
possible early-warning system.

Spec reference: docs/slesh-integration-roadmap.md §B2.8.
"""
from __future__ import annotations

import pytest

from app.modules.pos.schemas import (
    Brand,
    Category,
    Order,
    Product,
    Shop,
)


# ─── 1. Brand ───────────────────────────────────────────────────────────────

def test_brand_parses_real_response(slesh_fixture):
    """Brand schema accepts the real /brand/my response shape."""
    raw = slesh_fixture("brand_my")
    brand = Brand.model_validate(raw)

    assert brand.id == "6650c69e25fcbf370f6fcc16"
    assert brand.name == "Sundance"
    assert brand.is_enabled is True


def test_brand_pythonic_alias_mapping(slesh_fixture):
    """Slesh's underscore-prefixed fields map to Pythonic names."""
    raw = slesh_fixture("brand_my")
    brand = Brand.model_validate(raw)

    # _id -> id
    assert hasattr(brand, "id")
    assert brand.id == raw["_id"]

    # _createdAt -> created_at
    assert hasattr(brand, "created_at")
    assert brand.created_at == raw["_createdAt"]


def test_brand_lenient_with_unknown_fields(slesh_fixture):
    """Unknown Slesh fields don't crash parsing; they go into model_extra."""
    raw = slesh_fixture("brand_my")
    brand = Brand.model_validate(raw)

    # billing/images/configuration are real Slesh fields we don't model
    assert brand.model_extra is not None
    assert "billing" in brand.model_extra
    assert "images" in brand.model_extra


# ─── 2. Shop (paginated docs envelope) ──────────────────────────────────────

def test_shop_paginated_envelope_shape(slesh_fixture):
    """Shop responses use the {docs, total, hasNextPage} envelope."""
    raw = slesh_fixture("shop_my")

    assert isinstance(raw, dict)
    assert "docs" in raw
    assert "total" in raw
    assert "hasNextPage" in raw
    assert isinstance(raw["docs"], list)


def test_shops_parse_from_envelope(slesh_fixture):
    """Each shop in docs[] parses cleanly via the Shop schema."""
    raw = slesh_fixture("shop_my")
    shops = [Shop.model_validate(d) for d in raw["docs"]]

    assert len(shops) == len(raw["docs"]) > 0
    for s in shops:
        assert s.id, "shop must have an id"
        assert s.name, "shop must have a name"


def test_shop_address_is_nested_model(slesh_fixture):
    """Shop.address is a ShopAddress sub-model when present."""
    raw = slesh_fixture("shop_my")
    shops = [Shop.model_validate(d) for d in raw["docs"]]

    addresses_present = [s.address for s in shops if s.address is not None]
    assert addresses_present, "fixture should include at least one shop with an address"
    a = addresses_present[0]
    # City/country preserved (not PII), street-level redacted but present
    assert hasattr(a, "city")
    assert hasattr(a, "country")


# ─── 3. Category (plain list, NO docs envelope) ─────────────────────────────

def test_category_response_is_plain_list(slesh_fixture):
    """Categories endpoint returns a plain list, NOT a docs envelope.

    This is the API quirk discovered during B2.6 fixture recording — see
    decision log entry 2026-05-01.
    """
    raw = slesh_fixture("category_my")
    assert isinstance(raw, list), "category_my should be a plain list, not a dict"


def test_categories_parse_with_localized_name(slesh_fixture):
    """Category.name is a locale dict like {it: 'Cocktails', en: 'Cocktails'}."""
    raw = slesh_fixture("category_my")
    cats = [Category.model_validate(c) for c in raw]

    assert len(cats) > 0
    for c in cats:
        assert c.id
        assert isinstance(c.name, dict)
        # At least one of the canonical locales should be present
        assert any(k in c.name for k in ("it", "en")), (
            f"category {c.id} has no it/en locale: keys={list(c.name.keys())}"
        )


# ─── 4. Product (plain list) ────────────────────────────────────────────────

def test_product_response_is_plain_list(slesh_fixture):
    """Products endpoint also returns a plain list (same quirk as categories)."""
    raw = slesh_fixture("product_my")
    assert isinstance(raw, list)


def test_products_parse_with_price_in_cents(slesh_fixture):
    """Product.default_price is an integer in cents (e.g. 800 == €8.00)."""
    raw = slesh_fixture("product_my")
    prods = [Product.model_validate(p) for p in raw]

    assert len(prods) > 0
    priced = [p for p in prods if p.default_price is not None]
    assert priced, "fixture should include at least one priced product"
    for p in priced:
        assert isinstance(p.default_price, int), (
            f"default_price must be int (cents), got {type(p.default_price).__name__}"
        )
        assert p.default_price >= 0


def test_product_type_enum(slesh_fixture):
    """Product._type maps to 'physical' or 'digital' (Slesh enum)."""
    raw = slesh_fixture("product_my")
    prods = [Product.model_validate(p) for p in raw]
    types = {p.type for p in prods}
    assert types.issubset({"physical", "digital"}), (
        f"unexpected product types: {types}"
    )


# ─── 5. Order — the critical one (the polling worker depends on this) ──────

def test_order_paginated_envelope_with_total(slesh_fixture):
    """Order responses use the docs envelope with a meaningful total count."""
    raw = slesh_fixture("order_brand_my")
    assert isinstance(raw, dict)
    assert raw["total"] >= 0
    assert isinstance(raw["docs"], list)


def test_orders_parse_from_envelope(slesh_fixture):
    """Each order in docs[] parses cleanly via the Order schema."""
    raw = slesh_fixture("order_brand_my")
    orders = [Order.model_validate(d) for d in raw["docs"]]

    assert len(orders) == len(raw["docs"]) > 0
    for o in orders:
        assert o.id
        assert o.type in ("cash-desk", "express", "experience")


def test_order_cart_amounts_money_typing(slesh_fixture):
    """CartLine: gross_amount is int (clean cents); net/vat may be float."""
    raw = slesh_fixture("order_brand_my")
    orders = [Order.model_validate(d) for d in raw["docs"]]

    cart_lines = [line for o in orders for line in o.cart]
    assert cart_lines, "fixture orders should have at least one cart line"

    for line in cart_lines:
        # gross_amount is clean int cents
        assert isinstance(line.gross_amount, int)
        # net_amount and vat_amount may be float (VAT-split fractional)
        if line.net_amount is not None:
            assert isinstance(line.net_amount, (int, float))
        if line.vat_amount is not None:
            assert isinstance(line.vat_amount, (int, float))


def test_order_user_can_be_str_or_dict(slesh_fixture):
    """Order.user accepts either a populated User object or a bare id string.

    This is the API quirk discovered during B2.6 fixture validation — Slesh
    sometimes returns just the user_id string instead of a populated object.
    """
    raw = slesh_fixture("order_brand_my")
    orders = [Order.model_validate(d) for d in raw["docs"]]

    seen_types = {type(o.user).__name__ for o in orders if o.user is not None}
    # We're not asserting which one we see — depends on fixture redaction —
    # only that whatever we got didn't crash the schema.
    assert seen_types.issubset({"User", "str", "NoneType"}), (
        f"unexpected user types: {seen_types}"
    )


def test_order_shop_is_optional(slesh_fixture):
    """Order.shop may be missing on some orders (real Slesh quirk).

    Discovered during B2.6 fixture validation. Without this flexibility,
    parsing would crash on orders that Slesh elides the shop field for.
    """
    raw = slesh_fixture("order_brand_my")
    # The model_validate call MUST NOT raise — that is the test.
    [Order.model_validate(d) for d in raw["docs"]]


def test_order_payment_type_in_known_set(slesh_fixture):
    """Order.payment._type is one of the known payment methods."""
    raw = slesh_fixture("order_brand_my")
    orders = [Order.model_validate(d) for d in raw["docs"]]
    payments = [o.payment for o in orders if o.payment is not None]
    assert payments, "fixture orders should include at least one with payment"
    known = {"stripe", "adyen", "token", "cash", "card", "tap-to-pay", "mixed"}
    for p in payments:
        assert p.type in known, f"unknown payment type: {p.type}"


def test_order_experience_reference(slesh_fixture):
    """Order._experience embeds {_id, name} of the Sundance edition."""
    raw = slesh_fixture("order_brand_my")
    orders = [Order.model_validate(d) for d in raw["docs"]]
    with_exp = [o for o in orders if o.experience is not None]
    assert with_exp, "fixture should include orders with embedded experience"
    for o in with_exp:
        assert o.experience.id, "experience must have an id"


# ─── 6. Cross-schema: lenient strategy is uniform across all models ────────

@pytest.mark.parametrize("model_class,fixture_name,extract_first", [
    (Brand,    "brand_my",       lambda raw: raw),
    (Shop,     "shop_my",        lambda raw: raw["docs"][0]),
    (Category, "category_my",    lambda raw: raw[0]),
    (Product,  "product_my",     lambda raw: raw[0]),
    (Order,    "order_brand_my", lambda raw: raw["docs"][0]),
])
def test_all_models_accept_unknown_fields(slesh_fixture, model_class, fixture_name, extract_first):
    """Every Slesh schema is lenient: unknown fields go to model_extra, no crash.

    This guards against a future "let's tighten the schemas to extra=forbid"
    refactor — that would break our Sundance survival strategy.
    """
    raw = slesh_fixture(fixture_name)
    obj = extract_first(raw)
    instance = model_class.model_validate(obj)
    # The presence of model_extra is what matters; its content is incidental
    assert instance.model_extra is not None
