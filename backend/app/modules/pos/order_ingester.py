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

3. **Refunded lines are recorded for audit but don't decrement stock.**
   When Slesh marks a line as `status='refunded'`, we skip it (the
   primary ingestion of the original sale already happened). A later
   compensating transaction will be added in B7 if needed.

4. **DRINK-only ingestion.**
   StockTransactionService.ingest_sale() validates that product_type==DRINK.
   Food/Supply lines are skipped here with a debug log — they don't
   participate in our recipe-cascade ledger today.

Spec: docs/slesh-integration-roadmap.md §B6.3
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
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
        bar = await _find_bar_by_slesh_id(db, tenant_id, shop_ref.id)
        cache.bars[shop_ref.id] = bar
    if bar is None:
        result.lines_skipped += result.lines_total
        result.skip_reasons.append(f"no bar matched shop {shop_ref.id}")
        logger.warning(
            "ingest_order %s: skipped — no bar matched shop %s (%s). "
            "Run reference sync to refresh shop linkages.",
            order.id, shop_ref.id, shop_ref.name or "?",
        )
        return result

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

    logger.info("ingest_order: %s", result)
    return result


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

    # Skip refunded lines — original sale was already ingested in a
    # prior poll. Compensating transactions land in B7.
    if line.status == "refunded":
        result.lines_skipped += 1
        result.skip_reasons.append(f"line {line.id}: status=refunded")
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

    # ingest_sale validates DRINK only — short-circuit other types here
    # so we don't pollute the service's error logs.
    if product.product_type != ProductType.DRINK:
        result.lines_skipped += 1
        result.skip_reasons.append(
            f"line {line.id}: product_type={product.product_type.value} (only DRINK ingested)"
        )
        return

    # Build the ingest request
    request = SaleIngestRequest(
        event_id     = event_id,
        bar_id       = bar.id,
        product_id   = product.id,
        qty          = Decimal("1"),               # one cart line = one drink
        price_cents  = int(line.gross_amount),     # already cents (int) per schema
        source       = TransactionSource.SLESH_POS,
        source_idempotency_key = f"slesh:{order.id}:{line.id}",
        payment_type = payment_type,
    )

    sale_result = await service.ingest_sale(tenant_id=tenant_id, data=request)

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
