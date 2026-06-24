"""Slesh Order → stock_transactions ingestion.

This module is the BOUNDARY between Slesh's order shape and our
stock_transactions ledger. It does ONE thing per cart line:

  Slesh Order.cart[i] → SaleIngestRequest → StockTransactionService.ingest_sale()

The heavy lifting (cascade, deficit handling, idempotency replay,
parent/child transactions) lives in StockTransactionService. We just
adapt the data shape and delegate.

DESIGN CHOICES:

1. **One ingest call per cart line, not per order.**
   Each line has its own idempotency key (slesh:{order_id}:{line_id}).
   This means a partial refund on one line doesn't invalidate the others.

2. **Skip + log on missing references.**
   If a Slesh shop has no matching `bars.slesh_negozio_id`, we skip the
   ENTIRE order and log a warning. We never want to crash the poller.
   Same for products without a matching `external_pos_id`.
   The reference sync (B5) is responsible for keeping linkages fresh;
   the ingester is just an observer.

3. **Refunded lines update the existing row's `pos_line_status`.**
   When Slesh marks a line as `status='refunded'`, we UPDATE the row
   that was written in a prior poll (when it was still 'confirmed'),
   flipping its `pos_line_status` to 'refunded'. Aggregation queries
   in event_kpi_service.py and category_totals_service.py filter on
   `pos_line_status = 'confirmed'`, so refunded lines stop contributing
   to revenue without losing the audit trail.

4. **DRINK-only ingestion.**
   StockTransactionService.ingest_sale() validates that product_type==DRINK.
   Food/Supply lines are skipped here with a debug log — they don't
   participate in our recipe-cascade ledger today.

Spec: docs/slesh-integration-roadmap.md §B6.3
"""
from __future__ import annotations

from datetime import datetime as _dt_datetime, timezone as _dt_timezone
from sqlalchemy.dialects.postgresql import insert as _pg_insert

from app.modules.events.models import EventOrder as _EventOrder
from app.modules.bars.device_model import BarDevice as _BarDevice

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models                  import Bar
from app.modules.products.models              import Product, ProductType
from app.modules.stock_transactions.schemas   import SaleIngestRequest
from app.modules.stock_transactions.models    import TransactionSource

if TYPE_CHECKING:
    from app.modules.pos.schemas                       import Order
    from app.modules.stock_transactions.service        import StockTransactionService

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Slesh payment.type → our PaymentType enum
# ─────────────────────────────────────────────────────────────────────
# Slesh sends payment.type as a free string with 7 documented values.
# We map them 1:1 to our PaymentType enum, with one rename:
# Slesh\'s "tap-to-pay" → our "tap_to_pay" (Postgres ENUMs cannot have
# hyphens). Unknown values map to None — defensive, and the column is
# nullable. A warning is logged once per unknown value (deduped).

from app.modules.stock_transactions.models import PaymentType as _PaymentType

_PAYMENT_TYPE_MAP: dict[str, _PaymentType] = {
    "stripe":     _PaymentType.STRIPE,
    "adyen":      _PaymentType.ADYEN,
    "token":      _PaymentType.TOKEN,
    "cash":       _PaymentType.CASH,
    "card":       _PaymentType.CARD,
    "tap-to-pay": _PaymentType.TAP_TO_PAY,
    "tap_to_pay": _PaymentType.TAP_TO_PAY,
    "mixed":      _PaymentType.MIXED,
}
_UNKNOWN_PAYMENT_TYPES_SEEN: set[str] = set()


def _map_payment_type(slesh_type: str | None) -> _PaymentType | None:
    if slesh_type is None:
        return None
    key = slesh_type.strip().lower()
    if key in _PAYMENT_TYPE_MAP:
        return _PAYMENT_TYPE_MAP[key]
    if key not in _UNKNOWN_PAYMENT_TYPES_SEEN:
        _UNKNOWN_PAYMENT_TYPES_SEEN.add(key)
        logger.warning(
            "ingest: unknown Slesh payment.type %r — column will be NULL. "
            "Update _PAYMENT_TYPE_MAP in order_ingester.py.",
            slesh_type,
        )
    return None


# ─────────────────────────────────────────────────────────────────────
# Lookup cache
# ─────────────────────────────────────────────────────────────────────
# Live polling sees ~5-30 orders per cycle and re-issues the same lookups
# for repeat products/bars. Backfill sees thousands of orders, with many
# (food/supply) lines that we skip after the lookup. Without a cache,
# each line = 1 DB roundtrip. With a cache, each *distinct* product/bar
# = 1 DB roundtrip per ingest_order session.
#
# Cache lives for ONE ingest_order call (per-order). The caller (B6
# polling worker) creates a fresh cache per chunk via the optional
# `cache` parameter. If no cache is passed, we make one locally — keeps
# the function safe to call standalone.

class _LookupCache:
    """Per-batch cache keyed by external_id (Slesh _id strings).

    Two maps: products and bars. Values are SQLAlchemy ORM objects or
    None (negative caching — remembers IDs that don't exist in our DB
    so we don't re-query for them either).
    """
    def __init__(self) -> None:
        self.products: dict[str, "Product | None"] = {}
        self.bars:     dict[str, "Bar | None"]     = {}

    @property
    def stats(self) -> str:
        return (
            f"products: {len(self.products)} cached, "
            f"bars: {len(self.bars)} cached"
        )


# ─────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────
@dataclass
class IngestResult:
    """Per-order ingestion outcome — returned to the polling worker for logging."""
    order_id:         str               = ""
    lines_total:      int               = 0   # how many cart lines the order had
    lines_ingested:   int               = 0   # ingest_sale called successfully
    lines_skipped:    int               = 0   # food/supply/refunded/missing-ref
    lines_replayed:   int               = 0   # idempotency hit, no new write
    lines_errors:     int               = 0
    skip_reasons:     list[str]         = field(default_factory=list)
    error_messages:   list[str]         = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"order={self.order_id[:8]}.. "
            f"total={self.lines_total} "
            f"ingested={self.lines_ingested} "
            f"replayed={self.lines_replayed} "
            f"skipped={self.lines_skipped} "
            f"errors={self.lines_errors}"
        )


# ─────────────────────────────────────────────────────────────────────
# Public API — ingest one Slesh order
# ─────────────────────────────────────────────────────────────────────
async def ingest_order(
    *,
    db:        AsyncSession,
    order:     "Order",
    event_id:  UUID,
    tenant_id: UUID,
    service:   "StockTransactionService",
    cache:     "_LookupCache | None" = None,
) -> IngestResult:
    """Ingest a single Slesh Order into stock_transactions.

    Args:
        db:        Open async session (the caller manages commits).
        order:     Parsed Slesh Order (Pydantic model from schemas.py).
        event_id:  Which XProject event these lines belong to.
        tenant_id: Tenant scope.
        service:   Constructed StockTransactionService bound to `db`.

    Returns:
        IngestResult with detailed counts.

    The function NEVER raises on per-line errors — it logs and counts.
    The polling worker decides whether to retry the whole batch based
    on the aggregate IngestResult.
    """
    result = IngestResult(order_id=order.id, lines_total=len(order.cart))
    if cache is None:
        cache = _LookupCache()

    # Resolve our local bar from the Slesh shop reference.
    # If the order has no shop or we can't match it, skip the whole order.
    shop_ref = order.shop
    if shop_ref is None or isinstance(shop_ref, str):
        result.lines_skipped += result.lines_total
        result.skip_reasons.append("order has no embedded shop reference")
        logger.warning("ingest_order %s: skipped — no shop reference", order.id)
        return result

    if shop_ref.id in cache.bars:
        bar = cache.bars[shop_ref.id]
    else:
        bar = await _resolve_bar(db, tenant_id, event_id, shop_ref.id)
        cache.bars[shop_ref.id] = bar

    # Resolve payment type once per order — same value applies to all cart lines.
    payment_type = (
        _map_payment_type(order.payment.type) if order.payment is not None else None
    )

    # Per cart line, build a SaleIngestRequest and delegate.
    for line in order.cart:
        try:
            await _ingest_line(
                db=db, order=order, line=line, bar=bar,
                event_id=event_id, tenant_id=tenant_id, service=service,
                result=result, cache=cache, payment_type=payment_type,
            )
        except Exception as exc:    # noqa: BLE001 — log everything, never crash the poller
            result.lines_errors += 1
            result.error_messages.append(f"{line.id}: {type(exc).__name__}: {exc}")
            logger.exception(
                "ingest_order %s cart-line %s: unexpected failure", order.id, line.id,
            )

    # ── Phase 1b: write per-order summary row (revenue breakdown) ──
    # UPSERT on (tenant_id, slesh_order_id) — Slesh re-emits during
    # refunds and payment updates are idempotent.
    _confirmed = sum(1 for ln in order.cart if ln.status != "refunded")
    _refunded  = sum(1 for ln in order.cart if ln.status == "refunded")
    _slesh_shop_id = shop_ref.id if not isinstance(shop_ref, str) else shop_ref

    def _r(v):
        """Round optional float (Slesh VAT splits arrive as fractional cents) → int cents."""
        return None if v is None else int(round(v))

    # Preserve operator + user from the parsed Slesh order. Until Phase 3
    # (Jun 21 2026) this column was always NULL, which meant we had no
    # way to link a sale back to the device that made it — bar_devices
    # rows never lit up. Now stored as a small jsonb blob; full raw
    # order doc is intentionally NOT stored to keep row size manageable.
    _raw_extras = {}
    _op = getattr(order, "operator", None)
    if _op is not None and not isinstance(_op, str):
        _raw_extras["operator"] = _op.model_dump(mode="json", exclude_none=True)
    elif isinstance(_op, str):
        _raw_extras["operator"] = {"_id": _op}
    _u = getattr(order, "user", None)
    if _u is not None and not isinstance(_u, str):
        _raw_extras["user"] = _u.model_dump(mode="json", exclude_none=True)
    elif isinstance(_u, str):
        _raw_extras["user"] = {"_id": _u}

    _eo_values = dict(
        tenant_id=tenant_id,
        event_id=event_id,
        slesh_order_id=order.id,
        raw_extras=_raw_extras or None,
        slesh_shop_id=_slesh_shop_id,
        bar_id=bar.id if bar is not None else None,
        order_type=getattr(order, "type", "experience"),
        subtotal_cents=     _r(getattr(order, "subtotal",                 None)),
        vat_cents=          _r(getattr(order, "cart_vat_amount",          None)),
        deposit_cents=      _r(getattr(order, "cart_deposit_amount",      None)),
        fiscal_gross_cents= _r(getattr(order, "cart_fiscal_gross_amount", None)),
        fiscal_net_cents=   _r(getattr(order, "cart_fiscal_net_amount",   None)),
        discount_cents=     _r(getattr(order, "cart_discount_amount",     None)),
        payment_type=payment_type.value if payment_type is not None else None,
        cart_line_count=len(order.cart),
        confirmed_line_count=_confirmed,
        refunded_line_count=_refunded,
        created_at_slesh=_dt_datetime.fromtimestamp(
            getattr(order, "created_at", 0) / 1000, tz=_dt_timezone.utc,
        ),
    )
    _eo_stmt = (
        _pg_insert(_EventOrder)
        .values(**_eo_values)
        .on_conflict_do_update(
            index_elements=["tenant_id", "slesh_order_id"],
            set_={k: v for k, v in _eo_values.items()
                  if k not in ("tenant_id", "slesh_order_id", "event_id")},
        )
    )
    await db.execute(_eo_stmt)

    # ── Phase 3 (Jun 21 2026): mark the bar_device that processed
    # this order as active. Defensive: any failure in device
    # resolution must not propagate — the order itself is already
    # persisted, that's the critical path.
    if bar is not None:
        try:
            await _touch_bar_device(
                db=db,
                tenant_id=tenant_id,
                event_id=event_id,
                bar_id=bar.id,
                operator=getattr(order, "operator", None),
                order_created_at=_eo_values["created_at_slesh"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ingest_order %s: bar_device touch failed (non-fatal): %s",
                order.id, exc,
            )

    logger.info("ingest_order: %s", result)
    return result


# ─────────────────────────────────────────────────────────────────────
# Device touch — Phase 3 (Jun 21 2026)
# ─────────────────────────────────────────────────────────────────────
async def _touch_bar_device(
    *,
    db:        AsyncSession,
    tenant_id: UUID,
    event_id:  UUID,
    bar_id:    UUID,
    operator,                         # User | str | None (typed via schemas)
    order_created_at: _dt_datetime,
) -> None:
    """Mark the bar_device that processed an order as active.

    Resolution strategy:
      1) Match by slesh_operator_id (Mongo _id). Stable join key for any
         row written by a previous live touch.
      2) Match by slesh_operator_email. Excel-imported rows store the
         email in BOTH slesh_operator_id and slesh_operator_email columns
         (importer uses the email as a placeholder ID). When we find a
         row this way, we backfill the real Mongo _id into the id column
         so subsequent orders match on the cheaper (1) path.
      3) Lazy-create a new row. Defensive — Phase 4 wizard will pre-
         populate bar_devices for every event, but if an unmapped Slesh
         operator surfaces mid-event we still want it tracked rather
         than silently dropped.

    On every match, we set is_active=True and bump last_order_at only
    if the order is newer than the stored value. last_order_at MUST
    advance monotonically — out-of-order polls (rare but possible)
    should not rewind it.
    """
    if operator is None:
        return

    # Extract identity. Slesh sends operator as either a populated User
    # object or a bare Mongo _id string, depending on `populatedField`.
    if isinstance(operator, str):
        op_id, op_email = operator, None
    else:
        op_id = getattr(operator, "id", None)
        info  = getattr(operator, "info", None) or {}
        op_email = info.get("email") if isinstance(info, dict) else None

    if not op_id and not op_email:
        return  # nothing to match on

    # ── 1) Lookup by Mongo _id
    device = None
    if op_id:
        res = await db.execute(
            select(_BarDevice)
            .where(_BarDevice.tenant_id == tenant_id)
            .where(_BarDevice.event_id  == event_id)
            .where(_BarDevice.slesh_operator_id == op_id)
        )
        device = res.scalar_one_or_none()

    # ── 2) Fallback: lookup by email (Excel-imported rows)
    if device is None and op_email:
        res = await db.execute(
            select(_BarDevice)
            .where(_BarDevice.tenant_id == tenant_id)
            .where(_BarDevice.event_id  == event_id)
            .where(_BarDevice.slesh_operator_email == op_email)
        )
        device = res.scalar_one_or_none()
        if device is not None and op_id and device.slesh_operator_id != op_id:
            # Backfill the real Mongo _id so future orders hit path (1).
            device.slesh_operator_id = op_id

    # ── 3) Lazy-create if neither path matched
    if device is None:
        # We need a non-NULL email to create the row (schema constraint).
        # If Slesh only gave us an _id string with no email, fabricate a
        # placeholder so the row is creatable; Phase 4 wizard or a future
        # reconcile pass can correct it.
        if not op_email:
            op_email = f"{op_id}@unknown.slesh"
        device = _BarDevice(
            tenant_id            = tenant_id,
            event_id             = event_id,
            bar_id               = bar_id,
            slesh_operator_id    = op_id or op_email,
            slesh_operator_email = op_email,
            device_number        = None,
            role                 = "bartender",
            display_name         = None,
            is_active            = True,
            last_order_at        = order_created_at,
        )
        db.add(device)
        return  # nothing else to update — we just created it active

    # ── Existing row: flip active + bump last_order_at (monotonic)
    if not device.is_active:
        device.is_active = True
    if device.last_order_at is None or order_created_at > device.last_order_at:
        device.last_order_at = order_created_at


# ─────────────────────────────────────────────────────────────────────
# Per-line work — delegates to StockTransactionService.ingest_sale
# ─────────────────────────────────────────────────────────────────────
async def _ingest_line(
    *,
    db:        AsyncSession,
    order:     "Order",
    line,                                 # CartLine — type-only, no runtime import
    bar:       Bar,
    event_id:  UUID,
    tenant_id: UUID,
    service:   "StockTransactionService",
    result:    IngestResult,
    cache:     _LookupCache,
    payment_type: _PaymentType | None = None,
) -> None:
    """Ingest one cart line. Mutates `result` in place."""

    # Refunded lines: UPDATE the existing row (written in a prior poll
    # when it was 'confirmed') so aggregation queries exclude it. If no
    # row exists (refund happened within one poll cycle), the UPDATE is
    # a no-op and we accept the small audit gap.
    if line.status == "refunded":
        idem_key = f"slesh:{order.id}:{line.id}"
        await db.execute(
            text("""
                UPDATE stock_transactions
                SET pos_line_status = 'refunded'
                WHERE tenant_id = :tenant_id
                  AND source_idempotency_key = :idem_key
                  AND pos_line_status != 'refunded'
            """),
            {"tenant_id": tenant_id, "idem_key": idem_key},
        )
        result.lines_skipped += 1
        result.skip_reasons.append(f"line {line.id}: marked refunded")
        return

    # Resolve product. Skip if not in our catalog (run reference sync).
    if line.product in cache.products:
        product = cache.products[line.product]
    else:
        product = await _find_product_by_external_id(db, tenant_id, line.product)
        cache.products[line.product] = product
    if product is None:
        result.lines_skipped += 1
        result.skip_reasons.append(f"line {line.id}: no product matched {line.product}")
        logger.warning(
            "ingest_order %s line %s: skipped — no product matched %s. "
            "Run reference sync to refresh product linkages.",
            order.id, line.id, line.product,
        )
        return

    # Route by product type:
    #   DRINK -> ingest_sale (full recipe cascade)
    #   FOOD  -> ingest_food_sale (revenue-only, no cascade)
    #   other (supply/ingredient) -> skip
    if product.product_type not in (ProductType.DRINK, ProductType.FOOD):
        result.lines_skipped += 1
        result.skip_reasons.append(
            f"line {line.id}: product_type={product.product_type.value} (not drink/food)"
        )
        return

    # Build the ingest request (same shape for drink + food)
    request = SaleIngestRequest(
        event_id     = event_id,
        bar_id       = bar.id,
        product_id   = product.id,
        qty          = Decimal("1"),               # one cart line = one item
        price_cents  = int(line.gross_amount),     # already cents (int) per schema
        source       = TransactionSource.SLESH_POS,
        source_idempotency_key = f"slesh:{order.id}:{line.id}",
        payment_type = payment_type,
    )

    if product.product_type == ProductType.DRINK:
        sale_result = await service.ingest_sale(tenant_id=tenant_id, data=request)
    else:
        sale_result = await service.ingest_food_sale(tenant_id=tenant_id, data=request)

    if sale_result.idempotency_replay:
        result.lines_replayed += 1
    else:
        result.lines_ingested += 1


# ─────────────────────────────────────────────────────────────────────
# Lookup helpers — by linkage column, tenant-scoped
# ─────────────────────────────────────────────────────────────────────
async def _find_bar_by_slesh_id(
    db: AsyncSession, tenant_id: UUID, slesh_id: str,
) -> Bar | None:
    stmt = (
        select(Bar)
        .where(Bar.tenant_id == tenant_id)
        .where(Bar.slesh_negozio_id == slesh_id)
        .limit(1)
    )
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def _resolve_bar(
    db: AsyncSession, tenant_id: UUID, event_id: UUID, slesh_id: str,
) -> Bar:
    """Find a bar by Slesh shop_id, or auto-create a stub if none matches.

    The no-data-loss invariant: every Slesh sale must land on some bar
    so revenue is never silently dropped. If no XProject bar is mapped
    to this shop_id yet, we create one immediately with the truncated
    shop_id as its display name and auto_created=True. The owner
    reconciles via the Map Bars UI by renaming the stub or merging it
    into a properly-named bar (which transfers slesh_negozio_id and
    all StockTransaction rows to the target).
    """
    bar = await _find_bar_by_slesh_id(db, tenant_id, slesh_id)
    if bar is not None:
        return bar
    display = (
        f"{slesh_id[:8]}…{slesh_id[-4:]}"
        if len(slesh_id) > 12 else slesh_id
    )
    bar = Bar(
        tenant_id=tenant_id,
        event_id=event_id,
        name=display,
        slesh_negozio_id=slesh_id,
        bar_type="drinks",
        is_active=True,
        auto_created=True,
    )
    db.add(bar)
    await db.flush()
    logger.info(
        "ingester: auto-created bar %s (name=%s) for unmapped slesh_id=%s",
        bar.id, display, slesh_id,
    )
    return bar


async def _find_product_by_external_id(
    db: AsyncSession, tenant_id: UUID, external_id: str,
) -> Product | None:
    stmt = (
        select(Product)
        .where(Product.tenant_id == tenant_id)
        .where(Product.external_pos_id == external_id)
        .limit(1)
    )
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


__all__ = ["IngestResult", "ingest_order", "_LookupCache"]
