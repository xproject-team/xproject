"""Pydantic models mirroring Slesh API response shapes.

DESIGN PRINCIPLES:

1. **Faithful to Slesh.** Every field in these models corresponds to a field
   the Slesh API actually returns. We don't add or rename anything except via
   Pydantic aliases (Slesh's `_id` → our `id`, `_createdAt` → our `created_at`).

2. **Money as int (cents). Timestamps as int (Unix ms).** Schemas keep the
   raw Slesh wire format. Domain conversions (cents → Decimal, ms → datetime,
   localized name → string) happen in `converters.py`, called explicitly at
   the boundary where Slesh data enters our system. This separation means a
   schema is a pure passport check; converters are domain logic.

3. **Lenient + visible.** All models accept unknown fields without raising
   (`extra="allow"`) AND log a warning once per unknown key. This protects
   us from a Slesh-side schema addition (e.g. a new `affiliateBonus` field
   shipped the day before Sundance) without going blind to it. The warning
   tells us to update the model when convenient — never under live pressure.

4. **No silent defaults.** Required fields have no default. Optional fields
   default to `None` explicitly. There are no empty-string fallbacks that
   would hide missing data from us.

5. **Forward references inside Order.** Order references CartLine, Payment,
   and User; we declare those above Order so import order is clean.

Spec reference: docs/slesh-integration-roadmap.md §B2 + Slesh OpenAPI spec
extracted on 2026-04-29 (api.slesh.it/docs).
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)


# Module-level tracker for unknown-field warnings.
# Pydantic v2 treats class attributes prefixed with `_` as private
# per-instance state (ModelPrivateAttr), so a true class-shared set must
# live outside the BaseModel subclass. This set is process-wide.
_WARNED_UNKNOWN_FIELDS: set[tuple[str, str]] = set()


# ────────────────────────────────────────────────────────────────────────
# Base model — shared config, unknown-field warning, alias support
# ────────────────────────────────────────────────────────────────────────
class _SleshModel(BaseModel):
    """Common base for all Slesh response models.

    Configures lenient parsing, accepts both Slesh's wire-format names
    (`_id`) and our Pythonic names (`id`) when constructing in code, and
    logs unknown fields exactly once per (model_class, field_name) pair so
    repeated arrivals (e.g. same unknown field across 1000 orders) don't
    flood the logs.
    """
    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        # Allow JSON-style dict input; we never serialize back to Slesh.
        validate_assignment=False,
    )

    @model_validator(mode="after")
    def _warn_unknown_fields(self) -> _SleshModel:
        """Log a one-time warning for any fields Slesh sent that we don't model."""
        if not self.model_extra:
            return self
        cls_name = type(self).__name__
        for unknown_key in self.model_extra:
            warned_key = (cls_name, unknown_key)
            if warned_key not in _WARNED_UNKNOWN_FIELDS:
                _WARNED_UNKNOWN_FIELDS.add(warned_key)
                logger.warning(
                    "Slesh response contains unknown field: %s.%s — "
                    "adapter is lenient and accepted it, but the schema "
                    "should be updated when convenient.",
                    cls_name, unknown_key,
                )
        return self


# ────────────────────────────────────────────────────────────────────────
# Brand — response from GET /brand/my
# ────────────────────────────────────────────────────────────────────────
class Brand(_SleshModel):
    """Top-level brand record (e.g. Sundance under Noma Group).

    Returned by GET /brand/my. Used for the verify_token health check.
    """
    id:           str  = Field(alias="_id")
    name:         str
    is_enabled:   bool = Field(alias="isEnabled", default=True)
    short_code:   str | None = Field(alias="_shortCode", default=None)
    created_at:   int  | None = Field(alias="_createdAt", default=None)  # Unix ms
    owner:        str  | None = Field(alias="_owner",     default=None)


# ────────────────────────────────────────────────────────────────────────
# Shop — items in GET /shop/my
# Maps 1:1 to our `bars` table via slesh_negozio_id.
# ────────────────────────────────────────────────────────────────────────
class ShopAddress(_SleshModel):
    """Optional sub-object with a shop's physical address."""
    formatted:     str | None = Field(alias="_formatted",   default=None)
    city:          str | None = Field(alias="_city",        default=None)
    country:       str | None = Field(alias="_country",     default=None)
    postal_code:   str | None = Field(alias="_postalCode",  default=None)
    latitude:      float | None = Field(alias="_latitude",  default=None)
    longitude:     float | None = Field(alias="_longitude", default=None)


class Shop(_SleshModel):
    """A point-of-sale location. Slesh terminology: 'shop'. XProject: 'bar'."""
    id:            str  = Field(alias="_id")
    name:          str
    is_enabled:    bool = Field(alias="isEnabled", default=True)
    address:       ShopAddress | None = None
    created_at:    int  | None = Field(alias="_createdAt", default=None)  # Unix ms
    owner:         str  | None = Field(alias="_owner",     default=None)


# ────────────────────────────────────────────────────────────────────────
# Category — items in GET /category/my
# ────────────────────────────────────────────────────────────────────────
class Category(_SleshModel):
    """Product category (e.g. 'Cocktails', 'Birra', 'Analcolici').

    `name` is a localized dict from Slesh: {it: 'Cocktails', en: 'Cocktails'}.
    The converters module picks a locale at the boundary.
    """
    id:           str = Field(alias="_id")
    name:         dict[str, str]
    is_enabled:   bool = Field(alias="isEnabled", default=True)
    created_at:   int  | None = Field(alias="_createdAt", default=None)


# ────────────────────────────────────────────────────────────────────────
# Product — items in GET /product/my
# ────────────────────────────────────────────────────────────────────────
class Product(_SleshModel):
    """A single sellable item — drink, food, voucher.

    `default_price` is in CENTS as an integer. €8.00 arrives as 800.
    Converter divides by 100 at the boundary.
    """
    id:                str = Field(alias="_id")
    name:              dict[str, str]
    type:              str = Field(alias="_type")  # "physical" | "digital"
    digital_type:      str | None = Field(alias="_digitalType", default=None)
    default_price:     int | None = Field(alias="defaultPrice", default=None)  # cents
    default_vat:       str | None = Field(alias="defaultVat",   default=None)  # VAT class
    category:          Category | str | None = None  # may be populated or just an id
    is_enabled:        bool = Field(alias="isEnabled", default=True)
    external_ref:      str | None = Field(alias="externalRef", default=None)
    created_at:        int | None = Field(alias="_createdAt",  default=None)


# ────────────────────────────────────────────────────────────────────────
# Order sub-objects — declared first so Order can reference them
# ────────────────────────────────────────────────────────────────────────
class CartLine(_SleshModel):
    """A single line item inside an order's `cart[]`.

    Each cart line becomes one row in our `stock_transactions` table after
    ingestion (B6). The pair (order_id, cart_line_id) is the idempotency
    key that protects against duplicate ingestion across poll overlaps.
    """
    id:             str = Field(alias="_id")
    product:        str = Field(alias="_product")           # product id
    product_name:   dict[str, str] | str | None = Field(alias="_productName", default=None)
    category_name:  dict[str, str] | str | None = Field(alias="_categoryName", default=None)
    gross_amount:   int = Field(alias="_grossAmount")       # cents (clean ints)
    # Net and VAT are floats — Slesh does not pre-round VAT splits
    # (a €10 line at 10% VAT splits as net=909.0909..., vat=90.909...).
    # Float here matches Slesh's wire format; converters round at boundary.
    net_amount:     float | None = Field(alias="_netAmount",  default=None)
    vat_amount:     float | None = Field(alias="_vatAmount",  default=None)
    vat:            str | None = Field(alias="_vat",        default=None)
    quantity:       int | None = None  # often implicit (1 line = 1 item)
    status:         str = "confirmed"  # "confirmed" | "refunded" — per-line
    is_digital:     bool | None = Field(alias="_isDigital", default=None)


class Payment(_SleshModel):
    """How an order was paid.

    `_type` distinguishes wristband-paid orders (token) from cash, card,
    tap-to-pay, and mixed. The Wristband Activity feature in B8 derives
    its dataset from orders where payment.type == 'token'.
    """
    type:            str = Field(alias="_type")  # stripe | adyen | token | cash | card | tap-to-pay | mixed
    status:          str | None = None           # successful | refunded | pending
    amount:          int | None = None           # cents
    # The physical wristband/card credential backing a token payment.
    # Distinct from `User.id` — comparing the two is how we learn whether
    # one band maps to one person or a shared group wallet.
    payment_token:   str | None = Field(alias="_paymentToken", default=None)


class User(_SleshModel):
    """Wristband holder or operator. Embedded inside Order.

    For wristband-paid orders, `tag` carries the NFC chip identifier and
    `info` (when present) carries the registered customer's profile.
    """
    id:    str | None = Field(alias="_id", default=None)
    type:  str | None = Field(alias="_type", default=None)  # "user" | "operator"
    tag:   str | None = None  # NFC wristband ID
    info:  dict[str, Any] | None = None  # name, surname, email, phone, etc.


class ShopRef(_SleshModel):
    """Embedded shop reference inside an Order (lighter than full Shop)."""
    id:    str = Field(alias="_id")
    name:  str | None = None


class ExperienceRef(_SleshModel):
    """Embedded experience (event) reference inside an Order."""
    id:    str = Field(alias="_id")
    name:  str | None = None


# ────────────────────────────────────────────────────────────────────────
# Order — items in GET /order/brand-my
# THE most important shape in the entire integration.
# ────────────────────────────────────────────────────────────────────────
class Order(_SleshModel):
    """A single transaction. The polling worker streams these every 30s.

    Note: Slesh returns three order-type variants (cash-desk, express,
    experience) with slightly different field shapes. This unified model
    captures the union — fields specific to one variant are typed as
    Optional. The `type` field tells the caller which variant they have.

    Key fields the ingestion pipeline uses:
      - id              → idempotency root
      - cart[].id       → idempotency leaf  (unique per line item)
      - shop.id         → maps to bars.slesh_negozio_id
      - created_at      → ledger timestamp (Unix ms → datetime at boundary)
      - cart[].product  → maps to products.external_pos_id
      - payment.type    → cash/card/wristband split
      - status          → "confirmed" | "completed" | "ready" | "refunded"
    """
    id:           str = Field(alias="_id")
    type:         str = Field(alias="_type")             # cash-desk | express | experience
    created_at:   int = Field(alias="_createdAt")        # Unix ms
    payed_at:     int | None = Field(alias="_payedAt", default=None)
    status:       str = "confirmed"
    # Top-level customer email — present on registered-account orders,
    # absent for guest/cash orders. Stronger cross-event anchor than
    # user.id since customers reuse an email across Slesh brands/events
    # more reliably than they reuse a Mongo account.
    customer_email: str | None = Field(alias="_customerEmail", default=None)

    # Shop is normally present but some order types may omit it
    shop:         ShopRef | str | None = Field(alias="_shop", default=None)
    experience:   ExperienceRef | None = Field(alias="_experience", default=None)

    cart:         list[CartLine] = Field(default_factory=list)
    payment:      Payment | None = None
    # user/operator may arrive as a populated dict OR as a bare string id
    # (depends on Slesh's `populatedField` query param). Schema accepts both.
    user:         User | str | None = None
    operator:     User | str | None = None

    # Aggregate amounts (Slesh computes these for convenience).
    # Gross is clean int cents; net/VAT contain VAT-split fractions (see CartLine).
    cart_gross_amount:        int | None   = Field(alias="__cartGrossAmount",       default=None)
    cart_net_amount:          float | None = Field(alias="__cartNetAmount",         default=None)
    cart_vat_amount:          float | None = Field(alias="__cartVatAmount",         default=None)
    cart_deposit_amount:      float | None = Field(alias="__cartDepositAmount",     default=None)
    cart_fiscal_gross_amount: float | None = Field(alias="__cartFiscalGrossAmount", default=None)
    cart_fiscal_net_amount:   float | None = Field(alias="__cartFiscalNetAmount",   default=None)
    cart_discount_amount:     float | None = Field(alias="__cartDiscountAmount",    default=None)
    subtotal:                 float | None = Field(alias="__subtotal",              default=None)
    discount:                 int | None   = Field(alias="_discount",                default=None)


# ────────────────────────────────────────────────────────────────────────
# Public API — what other modules import from here
# ────────────────────────────────────────────────────────────────────────
__all__ = [
    "Brand",
    "Shop",
    "ShopAddress",
    "Category",
    "Product",
    "CartLine",
    "Payment",
    "User",
    "ShopRef",
    "ExperienceRef",
    "Order",
]
