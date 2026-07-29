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

2. **Park + alert on an unmapped shop_id (Jul-19 sprint).**
   If a Slesh shop has no matching `bars.slesh_negozio_id`, we do NOT
   auto-create a bar (that silently produced phantom bars on Sundance
   Jul-5 — see order_ingester._resolve_bar's prior history). Instead the
   order is parked in `pending_shop_mappings`
   (pending_shop_mappings_service.park_unmapped_order) and a WARNING
   alert fires so the Owner can map it to a bar without SSH. Once
   resolved, every parked order replays through this same ingest path.
   Orders with NO shop reference at all (not even an unmapped id) are a
   separate, unrecoverable case — those are skipped outright, logged,
   and never parked (there's no shop_id to key the parking row on).
   Products without a matching `external_pos_id` are skipped the same
   way; the reference sync (B5) is responsible for keeping those
   linkages fresh.

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
from app.modules.pos.models import IngestionLineError as _IngestionLineError

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models                  import Bar
from app.modules.products.models              import Product, ProductType
from app.modules.stock_transactions.schemas   import SaleIngestRequest
from app.modules.stock_transactions.models    import TransactionSource
from app.modules.pos.pending_shop_mappings_service import park_unmapped_order

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
# Identity field extraction — THE single source of truth
# ─────────────────────────────────────────────────────────────────────
# Both the live poller (ingest_order, below) and the historical identity
# backfill (app/scripts/backfill_customer_identity.py) call this function.
# Do not re-derive this mapping anywhere else — a backfill with its own
# parallel copy of the extraction logic proves nothing about whether the
# live path actually works.
@dataclass
class IdentityFields:
    """Everything derivable from a parsed Slesh Order about who made it."""
    raw_extras_user:     dict | None   # -> event_orders.raw_extras['user']
    raw_extras_operator: dict | None   # -> event_orders.raw_extras['operator']
    customer_email:      str  | None   # -> event_orders.customer_email (normalized)
    payment_token:       str  | None   # -> event_orders.payment_token


def extract_identity_fields(order: "Order") -> IdentityFields:
    """Pull operator/user (for raw_extras) and the two identity columns
    out of a parsed Slesh Order. user/operator may arrive as a populated
    object or a bare string id, depending on Slesh's `populatedField`
    query param — handle both the same way we always have.

    customer_email is normalized (lowercase + trimmed) here, at the one
    point every caller goes through — never normalize it anywhere else.
    """
    def _as_extras_blob(value) -> dict | None:
        if value is None:
            return None
        if isinstance(value, str):
            return {"_id": value}
        return value.model_dump(mode="json", exclude_none=True)

    customer_email = getattr(order, "customer_email", None)
    if customer_email:
        customer_email = customer_email.strip().lower() or None

    payment_token = None
    if order.payment is not None:
        payment_token = getattr(order.payment, "payment_token", None)

    return IdentityFields(
        raw_extras_user=_as_extras_blob(getattr(order, "user", None)),
        raw_extras_operator=_as_extras_blob(getattr(order, "operator", None)),
        customer_email=customer_email,
        payment_token=payment_token,
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
# Durable per-line error trace (2026-07-29 hardening)
# ─────────────────────────────────────────────────────────────────────
async def _persist_line_error(
    *, tenant_id: UUID, event_id: UUID, slesh_order_id: str, slesh_line_id: str,
    error_type: str, error_message: str,
) -> None:
    """Best-effort durable record of a per-line ingestion failure.

    Uses a FRESH session, independent of the caller's — the failure that
    triggered this may itself be a DB error that has left the caller's
    transaction unusable, so we can't reuse it. Swallows its own
    exceptions: a failure to log must never be able to cause a second,
    unrelated failure in the ingestion path.
    """
    try:
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            db.add(_IngestionLineError(
                tenant_id=tenant_id,
                event_id=event_id,
                slesh_order_id=slesh_order_id,
                slesh_line_id=slesh_line_id,
                error_type=error_type,
                error_message=error_message[:4000],
            ))
            await db.commit()
    except Exception:  # noqa: BLE001 — logging must never crash ingestion
        logger.exception(
            "failed to persist ingestion line error for order=%s line=%s (non-fatal)",
            slesh_order_id, slesh_line_id,
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
        if bar is not None:
            cache.bars[shop_ref.id] = bar

    if bar is None:
        # Unmapped shop_id — park instead of auto-creating a phantom bar
        # (Jul-19 sprint fix). Not cached: a subsequent order in the same
        # batch should re-check in case an earlier order in this same
        # ingest run somehow resolved it (defensive; normally resolution
        # only happens via the operator-facing endpoint, out of band).
        await park_unmapped_order(
            db=db, tenant_id=tenant_id, event_id=event_id,
            slesh_shop_id=shop_ref.id, order=order,
        )
        result.lines_skipped += result.lines_total
        result.skip_reasons.append(
            f"order parked — unmapped shop_id {shop_ref.id}"
        )
        logger.info(
            "ingest_order %s: parked — unmapped shop_id=%s",
            order.id, shop_ref.id,
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
            await _persist_line_error(
                tenant_id=tenant_id, event_id=event_id,
                slesh_order_id=order.id, slesh_line_id=line.id,
                error_type=type(exc).__name__, error_message=str(exc),
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
    _identity = extract_identity_fields(order)
    _raw_extras = {}
    if _identity.raw_extras_operator is not None:
        _raw_extras["operator"] = _identity.raw_extras_operator
    if _identity.raw_extras_user is not None:
        _raw_extras["user"] = _identity.raw_extras_user

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
        customer_email=_identity.customer_email,
        payment_token=_identity.payment_token,
    )
    _eo_insert = _pg_insert(_EventOrder).values(**_eo_values)
    _eo_update_set = {
        k: v for k, v in _eo_values.items()
        if k not in ("tenant_id", "slesh_order_id", "event_id")
    }
    # Identity columns are coalesce-only: once captured, a later poll (or
    # the backfill script) must never clobber an existing value with NULL
    # or with a different one, since the two are the only durable customer
    # anchors we have. Every other column keeps the existing always-
    # overwrite behavior (they reflect current order state, e.g. refund
    # counts, which legitimately change between polls).
    _eo_update_set["customer_email"] = func.coalesce(
        _EventOrder.customer_email, _eo_insert.excluded.customer_email,
    )
    _eo_update_set["payment_token"] = func.coalesce(
        _EventOrder.payment_token, _eo_insert.excluded.payment_token,
    )
    _eo_stmt = _eo_insert.on_conflict_do_update(
        index_elements=["tenant_id", "slesh_order_id"],
        set_=_eo_update_set,
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

    # ── Phase 4 (Jun 21 2026): re-classify auto-created bars as 'food'
    # if every product sold at them is FOOD. The ingester defaults
    # auto-created stubs to bar_type='drinks' because most events ARE
    # drink-dominated; this catches food trucks Omar forgot to configure
    # in the wizard. Defensive: non-fatal failure, critical path is the
    # sale ingest below.
    try:
        await _maybe_classify_bar_as_food(db=db, bar=bar, current_product=product)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ingest_order line %s: bar-type reclassification failed (non-fatal): %s",
            line.id, exc,
        )

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
) -> Bar | None:
    """Find a bar by Slesh shop_id. Returns None if no bar is mapped yet.

    Jul-19 sprint: this used to auto-create a phantom bar here (the
    no-data-loss invariant — every Slesh sale must land on SOME bar).
    That silently created unnamed bars three times during Sundance
    Jul-5 when food trucks came online mid-event, requiring manual
    SQL merges. The invariant now holds a different way: the caller
    (ingest_order) parks the order in pending_shop_mappings instead of
    dropping it, so no sale is lost — it just isn't attributed to a bar
    until the operator resolves the mapping (see
    pending_shop_mappings_service.py).
    """
    return await _find_bar_by_slesh_id(db, tenant_id, slesh_id)


async def _maybe_classify_bar_as_food(
    *,
    db: AsyncSession,
    bar: Bar,
    current_product: Product,
) -> None:
    """Re-classify an auto-created drinks stub as a food bar when warranted.

    Trigger conditions (all must hold):
      1. Bar was auto-created by the ingester (not wizard-defined). Wizard
         data is sacred — we never overwrite operator intent.
      2. Bar is still classified as 'drinks' (the default). Once flipped
         away from drinks, the check is skipped to keep this a one-shot
         operation (cheap on every order).
      3. The current cart line's product is product_type=food. A pure
         food bar can only be detected once at least one food product
         sells there. Drinks at a drinks bar early-exit at this gate.
      4. EVERY DISTINCT product previously sold at this bar is also
         product_type=food. Single positive check; a single drink sale
         in the bar's history disqualifies it.

    On a positive verdict, flips bar.bar_type to 'food' (single attribute
    set; the surrounding session commit persists it). On the next order
    arriving at the same bar, condition (2) skips this work entirely.

    Cheap SQL: bool_and over the distinct product_types seen at the bar,
    joined to the products table. Index on stock_transactions.bar_id +
    products.id (PK) means this is O(distinct products) per check, run
    at most ONCE per bar across its lifetime.
    """
    if not bar.auto_created or bar.bar_type != "drinks":
        return
    if current_product.product_type != ProductType.FOOD:
        return

    # Pure-food check: bool_and(product_type='food') across every distinct
    # product previously sold at this bar. This is true even for a bar
    # with zero prior transactions (NULL → treated as TRUE here, which we
    # want: a brand-new bar's first sale being food makes it food).
    from app.modules.stock_transactions.models import StockTransaction
    res = await db.execute(
        select(func.bool_and(Product.product_type == ProductType.FOOD))
        .select_from(StockTransaction)
        .join(Product, Product.id == StockTransaction.product_id)
        .where(StockTransaction.bar_id == bar.id)
    )
    all_food_so_far = res.scalar()  # bool | None
    # NULL means no prior transactions exist; current line is food, so
    # this becomes a pure-food bar by inference. Treat NULL as True.
    if all_food_so_far is None or all_food_so_far is True:
        bar.bar_type = "food"
        logger.info(
            "ingester: reclassified auto-created bar %s (name=%s) "
            "from drinks to food (all products at this bar are food)",
            bar.id, bar.name,
        )


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
