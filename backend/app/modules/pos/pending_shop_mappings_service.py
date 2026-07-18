"""Service layer for the phantom-bar defensive fix (Jul-19 sprint).

Root cause of the Sundance Jul-5 phantom-bar incidents: three food
trucks came online mid-event with no bar.slesh_negozio_id set. The
first order from each unmapped shop_id caused order_ingester._resolve_bar
to silently auto-create a phantom bar. Omar had to manually SQL-merge
phantoms into the real bars three times during the event.

Two responsibilities:
  1. park_unmapped_order — called from order_ingester.ingest_order() the
     moment an order arrives for a shop_id with no matching bar. Upserts
     the pending_shop_mappings row (see app/modules/pos/models.py) and
     fires/updates a WARNING alert so the Owner sees it without SSH.
  2. list_pending / resolve — the operator-facing side: list unresolved
     mappings for an event, and resolve one by linking a bar + replaying
     every parked order through the normal ingest_order() path (same
     recipe cascade, same idempotency guarantees as a live order).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.models import Alert
from app.modules.bars.models import Bar
from app.modules.pos.models import PendingShopMapping

if TYPE_CHECKING:
    from app.modules.pos.schemas import Order

logger = logging.getLogger(__name__)


# ─── Domain exceptions — mapped by the router to 4xx HTTPException ────────────

class PendingMappingNotFoundError(Exception):
    """Pending mapping not found in this tenant/event."""


class PendingMappingAlreadyResolvedError(Exception):
    """Cannot resolve a pending mapping that's already resolved."""


class BarNotFoundError(Exception):
    """The bar_id provided on resolve does not exist in this tenant."""


# ─── Raw-order field extraction ────────────────────────────────────────────────

def _extract_operator_email(order: "Order") -> str | None:
    """Best-effort operator email — order.operator, falling back to
    order.user. Both may arrive as a bare string id (no populated info)
    depending on Slesh's populatedField query param."""
    for candidate in (order.operator, order.user):
        if candidate is not None and not isinstance(candidate, str) and candidate.info:
            email = candidate.info.get("email")
            if email:
                return email
    return None


def _order_gross_cents(order: "Order") -> int:
    if order.cart_gross_amount is not None:
        return int(order.cart_gross_amount)
    return sum(line.gross_amount for line in order.cart)


# ─── Parking (called from the ingester) ────────────────────────────────────────

async def park_unmapped_order(
    db: AsyncSession,
    tenant_id: UUID,
    event_id: UUID,
    slesh_shop_id: str,
    order: "Order",
) -> PendingShopMapping:
    """Park one order for an unmapped shop_id instead of auto-creating a bar.

    Idempotent per order.id: the polling window's 60-second overlap (see
    app/modules/pos/poll_state.py) can hand us the same order more than
    once before the shop gets resolved — without this guard, order_count
    and total_gross_cents would inflate every poll cycle for the SAME
    orders, not just genuinely new ones.
    """
    stmt = select(PendingShopMapping).where(
        PendingShopMapping.tenant_id == tenant_id,
        PendingShopMapping.event_id == event_id,
        PendingShopMapping.slesh_shop_id == slesh_shop_id,
        PendingShopMapping.resolved_at.is_(None),
    )
    pending = (await db.execute(stmt)).scalar_one_or_none()

    gross_cents = _order_gross_cents(order)
    operator_email = _extract_operator_email(order)
    raw_order = order.model_dump(mode="json", by_alias=True)

    if pending is None:
        pending = PendingShopMapping(
            tenant_id=tenant_id,
            event_id=event_id,
            slesh_shop_id=slesh_shop_id,
            first_seen_at=datetime.now(timezone.utc),
            order_count=1,
            total_gross_cents=gross_cents,
            sample_operator_email=operator_email,
            parked_orders_json=[raw_order],
        )
        db.add(pending)
        await db.flush()
    else:
        already_parked_ids = {o.get("_id") for o in pending.parked_orders_json}
        if order.id not in already_parked_ids:
            pending.order_count += 1
            pending.total_gross_cents += gross_cents
            if pending.sample_operator_email is None and operator_email:
                pending.sample_operator_email = operator_email
            pending.parked_orders_json = [*pending.parked_orders_json, raw_order]
            await db.flush()

    await _fire_or_update_alert(db, tenant_id, pending)
    return pending


async def _fire_or_update_alert(
    db: AsyncSession, tenant_id: UUID, pending: PendingShopMapping,
) -> None:
    """Fire/update the unmapped-shop alert directly against the Alert
    table — bypassing AlertsService.create_alert()'s dedup, which is
    keyed on (tenant, event, bar_id, product_id, alert_type). Every
    unmapped-shop alert has bar_id=None and product_id=None, so that key
    can't distinguish two DIFFERENT unmapped shop_ids in the same event —
    it would incorrectly collapse Jul-5's three simultaneous food trucks
    onto a single alert. Same workaround already used for
    supplier_product-scoped depletion alerts (no native column for that
    discriminator either) — see fire_depletion_alerts() in
    app/modules/event_storage/bar_supplier_stock_service.py.

    alert_type reuses the existing 'system' enum value rather than adding
    a 5th one — there's no free-text 'category' column on Alert, so the
    discriminator lives in context_json.category instead.
    """
    stmt = select(Alert).where(
        Alert.tenant_id == tenant_id,
        Alert.event_id == pending.event_id,
        Alert.alert_type == "system",
        Alert.context_json["category"].astext == "unmapped_shop",
        Alert.context_json["slesh_shop_id"].astext == pending.slesh_shop_id,
        Alert.acknowledged_at.is_(None),
        Alert.auto_resolved_at.is_(None),
        Alert.expired_at.is_(None),
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    gross_eur = pending.total_gross_cents / 100.0
    message = (
        f"Unknown Slesh shop {pending.slesh_shop_id} has {pending.order_count} "
        f"orders (€{gross_eur:.2f}) waiting for bar mapping"
    )
    context: dict[str, Any] = {
        "category": "unmapped_shop",
        "slesh_shop_id": pending.slesh_shop_id,
        "pending_mapping_id": str(pending.id),
        "order_count": pending.order_count,
        "total_gross_cents": pending.total_gross_cents,
    }

    if existing is not None:
        existing.owner_message = message
        existing.context_json = context
        existing.version += 1
        await db.flush()
        return

    alert = Alert(
        tenant_id=tenant_id,
        event_id=pending.event_id,
        bar_id=None,
        product_id=None,
        alert_type="system",
        severity="warning",
        audience="owner_only",
        title="Unmapped Slesh shop needs a bar",
        owner_message=message,
        context_json=context,
    )
    db.add(alert)
    await db.flush()


# ─── Operator-facing: list + resolve ───────────────────────────────────────────

async def list_pending(
    db: AsyncSession, tenant_id: UUID, event_id: UUID,
) -> list[PendingShopMapping]:
    """Unresolved pending mappings for an event, oldest first."""
    stmt = (
        select(PendingShopMapping)
        .where(
            PendingShopMapping.tenant_id == tenant_id,
            PendingShopMapping.event_id == event_id,
            PendingShopMapping.resolved_at.is_(None),
        )
        .order_by(PendingShopMapping.first_seen_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def resolve(
    db: AsyncSession,
    tenant_id: UUID,
    event_id: UUID,
    pending_id: UUID,
    bar_id: UUID,
) -> dict[str, int]:
    """Link the pending shop_id to a bar and replay every parked order.

    Returns {"orders_replayed": N, "lines_replayed": M}.
    """
    pending = await db.get(PendingShopMapping, pending_id)
    if (
        pending is None
        or pending.tenant_id != tenant_id
        or pending.event_id != event_id
    ):
        raise PendingMappingNotFoundError()
    if pending.resolved_at is not None:
        raise PendingMappingAlreadyResolvedError()

    bar = await db.get(Bar, bar_id)
    if bar is None or bar.tenant_id != tenant_id:
        raise BarNotFoundError()

    bar.slesh_negozio_id = pending.slesh_shop_id

    pending.resolved_at = datetime.now(timezone.utc)
    pending.resolved_bar_id = bar_id

    # Late imports — avoid pulling the full ingestion stack into every
    # caller of this module (mirrors the lazy-import convention already
    # used in app/workers/tasks.py for the same reason).
    from app.modules.pos.order_ingester import _LookupCache, ingest_order
    from app.modules.pos.schemas import Order
    from app.modules.stock_transactions.service import StockTransactionService

    svc = StockTransactionService(db)
    cache = _LookupCache()
    orders_replayed = 0
    lines_replayed = 0
    for raw_order in pending.parked_orders_json:
        order = Order.model_validate(raw_order)
        result = await ingest_order(
            db=db, order=order, event_id=event_id, tenant_id=tenant_id,
            service=svc, cache=cache,
        )
        orders_replayed += 1
        lines_replayed += result.lines_ingested + result.lines_replayed
        if result.lines_errors:
            logger.warning(
                "pending_shop_mappings.resolve: order %s had %d line errors "
                "on replay: %s",
                order.id, result.lines_errors, result.error_messages,
            )

    # Auto-resolve the alert we fired while this was pending — the
    # condition no longer applies now that the bar is linked.
    alert_stmt = select(Alert).where(
        Alert.tenant_id == tenant_id,
        Alert.event_id == event_id,
        Alert.alert_type == "system",
        Alert.context_json["pending_mapping_id"].astext == str(pending.id),
        Alert.acknowledged_at.is_(None),
        Alert.auto_resolved_at.is_(None),
        Alert.expired_at.is_(None),
    )
    active_alert = (await db.execute(alert_stmt)).scalar_one_or_none()
    if active_alert is not None:
        active_alert.auto_resolved_at = datetime.now(timezone.utc)
        active_alert.version += 1

    await db.commit()

    logger.info(
        "pending_shop_mappings.resolve: pending=%s bar=%s orders_replayed=%d "
        "lines_replayed=%d",
        pending_id, bar_id, orders_replayed, lines_replayed,
    )
    return {"orders_replayed": orders_replayed, "lines_replayed": lines_replayed}
