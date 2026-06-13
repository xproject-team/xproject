"""Per-bar-per-supplier-product ml-depletion service.

Implements the worst-case high-recall depletion math locked with Hesam
on June 13 2026 for Sundance 14:

  For each StockTransaction with category C at bar B:
    For each EventCategoryIngredient rule with slesh_category=C
        applicable to bar B (bar_id NULL or bar_id == B):
      Subtract ml_per_sale from the supplier_product at bar B.

This systematically over-counts depletion (every ambiguous Signature
sale hits Vodka + Gin + Rum + Tequila simultaneously), producing ~Nx
alerts vs an accurate system. Omar accepts the noise; humans verify
in person when alerts fire. False positives << false negatives.

Returns per-(bar, supplier_product) rows ready for:
  - The /events/{id}/bar-supplier-stock endpoint
  - Auto-alert firing on threshold flips
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models import Bar
from app.modules.event_storage.models import (
    EventCategoryIngredient,
    EventStockBarAllocation,
    SupplierProduct,
)
from app.modules.products.models import Product
from app.modules.stock_transactions.models import StockTransaction, TransactionSource
from datetime import datetime, timezone
from sqlalchemy import and_
from app.modules.alerts.models import Alert

logger = logging.getLogger(__name__)


# ─── Status thresholds (read from rule, with sane defaults) ─────────
def _resolve_status(
    remaining_pct: float,
    threshold_pct_warn: float,
    threshold_pct_empty: float,
) -> str:
    """Status from remaining%, using the rule's warn/empty thresholds.

    consumed_pct = 100 - remaining_pct
    - consumed_pct >= threshold_pct_empty   → 'critical'
    - consumed_pct >= threshold_pct_warn    → 'low'
    - else                                  → 'healthy'
    """
    consumed_pct = 100.0 - remaining_pct
    if consumed_pct >= threshold_pct_empty:
        return "critical"
    if consumed_pct >= threshold_pct_warn:
        return "low"
    return "healthy"


@dataclass
class BarSupplierStockRow:
    bar_id:              UUID
    bar_name:            str
    supplier_product_id: UUID
    item_name:           str
    dispatched_units:    float   # in default_unit (e.g. 30 BO, 5 KAR, 15 FS)
    dispatched_ml:       float
    consumed_ml:         float
    # Split of total consumed_ml by attribution certainty:
    #   certain   = ml from sole-rule slesh_categories (e.g. GIN TONIC → only
    #               Beefeater is consumed, no ambiguity)
    #   uncertain = ml from multi-rule slesh_categories (e.g. SPRITZ → one
    #               of 5 spirits actually used; we worst-case all 5)
    # consumed_ml == consumed_ml_certain + consumed_ml_uncertain (always).
    consumed_ml_certain:   float
    consumed_ml_uncertain: float
    remaining_ml:        float
    remaining_pct:       float   # 0-100, clamped
    status:              str     # 'healthy' | 'low' | 'critical'
    threshold_pct_warn:  float
    threshold_pct_empty: float
    # True iff this supplier_product participates ONLY in sole-rule
    # slesh_categories (no uncertain attribution at all). E.g. Heineken
    # keg, Ichnusa keg, Prosecco DOCG — exact 1:1 depletion. False when at
    # least one category contributes worst-case ml (Beefeater participates
    # in GIN TONIC (sole) + DRINK + SIGNATURE — so accurate=False, but
    # consumed_ml_certain > 0 captures the GIN TONIC portion).
    accurate:            bool = False


async def compute_bar_supplier_stock(
    session: AsyncSession,
    tenant_id: UUID,
    event_id: UUID,
    bar_id: UUID | None = None,
) -> list[BarSupplierStockRow]:
    """Compute per-(bar, supplier_product) depletion math for an event.

    If bar_id is provided, returns rows only for that bar. Otherwise all
    bars in the event.

    Worst-case multi-deplete: each transaction may decrement multiple
    supplier_products simultaneously (every rule matching its category).
    """
    # 1. Fetch all allocations (the "dispatched" side)
    alloc_q = select(
        EventStockBarAllocation.bar_id,
        EventStockBarAllocation.supplier_product_id,
        EventStockBarAllocation.qty_allocated,
    ).where(
        EventStockBarAllocation.tenant_id == tenant_id,
        EventStockBarAllocation.event_id == event_id,
    )
    if bar_id is not None:
        alloc_q = alloc_q.where(EventStockBarAllocation.bar_id == bar_id)
    alloc_rows = (await session.execute(alloc_q)).all()

    # Aggregate dispatches per (bar, supplier_product) — history table can
    # have multiple rows per pair when Omar re-dispatches.
    dispatched_units: dict[tuple[UUID, UUID], Decimal] = {}
    for r in alloc_rows:
        key = (r.bar_id, r.supplier_product_id)
        dispatched_units[key] = dispatched_units.get(key, Decimal(0)) + r.qty_allocated

    if not dispatched_units:
        return []

    # 2. Fetch supplier_product metadata for ml math
    sp_ids = {sp_id for (_, sp_id) in dispatched_units.keys()}
    sp_rows = (await session.execute(
        select(SupplierProduct).where(SupplierProduct.id.in_(sp_ids))
    )).scalars().all()
    sp_by_id: dict[UUID, SupplierProduct] = {sp.id: sp for sp in sp_rows}

    # 3. Fetch bar names (one query)
    bar_ids = {b_id for (b_id, _) in dispatched_units.keys()}
    bar_rows = (await session.execute(
        select(Bar.id, Bar.name).where(Bar.id.in_(bar_ids))
    )).all()
    bar_name_by_id: dict[UUID, str] = {b.id: b.name for b in bar_rows}

    # 4. Fetch all category-ingredient rules for this event
    rules = (await session.execute(
        select(EventCategoryIngredient).where(
            EventCategoryIngredient.tenant_id == tenant_id,
            EventCategoryIngredient.event_id == event_id,
        )
    )).scalars().all()

    # Index rules by (slesh_category, supplier_product_id, bar_id-or-None)
    # Multiple rules can share (cat, sp) with different bar_id constraints.
    # rules_by_cat_sp: cat → sp → [list of (bar_id_filter, ml_per_sale, warn, empty)]
    rules_by_cat_sp: dict[str, dict[UUID, list]] = {}
    for rule in rules:
        rules_by_cat_sp.setdefault(rule.slesh_category, {}).setdefault(
            rule.supplier_product_id, []
        ).append((
            rule.bar_id,
            float(rule.ml_per_sale),
            float(rule.threshold_pct_warn),
            float(rule.threshold_pct_empty),
        ))

    # 5. Fetch transaction counts per (bar, product.name)
    # Slesh-only revenue transactions; qty=1 convention enforced in ingester.
    tx_q = (
        select(
            StockTransaction.bar_id,
            Product.name.label("product_name"),
        )
        .join(Product, Product.id == StockTransaction.product_id)
        .where(
            StockTransaction.tenant_id == tenant_id,
            StockTransaction.event_id == event_id,
            StockTransaction.source == TransactionSource.SLESH_POS,
        )
    )
    if bar_id is not None:
        tx_q = tx_q.where(StockTransaction.bar_id == bar_id)
    tx_rows = (await session.execute(tx_q)).all()

    # Count tx per (bar_id, product_name)
    tx_count: dict[tuple[UUID, str], int] = {}
    for r in tx_rows:
        k = (r.bar_id, r.product_name)
        tx_count[k] = tx_count.get(k, 0) + 1

    # 6. For each (bar, supplier_product) dispatched, compute consumed_ml.
    result: list[BarSupplierStockRow] = []
    # Precompute: how many rules exist per slesh_category in this event?
    # A supplier_product is accurately depleted only if every category it
    # participates in has exactly 1 rule (no parallel alternatives).
    rules_per_category: dict[str, int] = {}
    for rule in rules:
        rules_per_category[rule.slesh_category] = rules_per_category.get(rule.slesh_category, 0) + 1

    for (b_id, sp_id), dispatched_qty in dispatched_units.items():
        sp = sp_by_id.get(sp_id)
        if sp is None:
            continue   # orphan allocation (shouldn't happen with FK RESTRICT)
        units_per_pack = sp.units_per_pack or 1
        vol_per_unit_ml = sp.volume_per_unit_ml or 0
        dispatched_ml = float(dispatched_qty) * units_per_pack * vol_per_unit_ml
        if dispatched_ml <= 0:
            # E.g. CO2 canister has no meaningful ml; skip
            continue

        # Sum consumed ml across all rules touching this supplier_product,
        # split by attribution certainty (sole-rule vs multi-rule categories).
        consumed_ml_certain = 0.0
        consumed_ml_uncertain = 0.0
        warn_pct = 70.0
        empty_pct = 100.0
        for cat, sp_map in rules_by_cat_sp.items():
            if sp_id not in sp_map:
                continue
            cat_is_sole = rules_per_category.get(cat, 0) == 1
            for (rule_bar_id, ml_per_sale, w, e) in sp_map[sp_id]:
                # If rule is restricted to a specific bar, only count tx at that bar.
                if rule_bar_id is not None and rule_bar_id != b_id:
                    continue
                tx_n = tx_count.get((b_id, cat), 0)
                if tx_n > 0:
                    bucket = consumed_ml_certain if cat_is_sole else consumed_ml_uncertain
                    bucket += tx_n * ml_per_sale
                    if cat_is_sole:
                        consumed_ml_certain = bucket
                    else:
                        consumed_ml_uncertain = bucket
                # Track the most relevant threshold (use the last found per sp;
                # all rules for one sp usually share thresholds).
                warn_pct = w
                empty_pct = e
        consumed_ml = consumed_ml_certain + consumed_ml_uncertain

        remaining_ml = max(dispatched_ml - consumed_ml, 0.0)
        remaining_pct = (remaining_ml / dispatched_ml * 100.0) if dispatched_ml else 0.0
        status = _resolve_status(remaining_pct, warn_pct, empty_pct)

        # Accuracy: SP is accurate iff every rule touching it sits in a
        # slesh_category that has only ONE rule total (no parallel options).
        is_accurate = True
        for cat, sp_map in rules_by_cat_sp.items():
            if sp_id in sp_map:
                if rules_per_category.get(cat, 0) > 1:
                    is_accurate = False
                    break
        result.append(BarSupplierStockRow(
            bar_id=b_id,
            bar_name=bar_name_by_id.get(b_id, "(unknown)"),
            supplier_product_id=sp_id,
            item_name=sp.item_name,
            dispatched_units=float(dispatched_qty),
            dispatched_ml=dispatched_ml,
            consumed_ml=consumed_ml,
            consumed_ml_certain=consumed_ml_certain,
            consumed_ml_uncertain=consumed_ml_uncertain,
            remaining_ml=remaining_ml,
            remaining_pct=remaining_pct,
            status=status,
            threshold_pct_warn=warn_pct,
            threshold_pct_empty=empty_pct,
            accurate=is_accurate,
        ))

    # Sort: bar name, then most-depleted first
    result.sort(key=lambda r: (r.bar_name, r.remaining_pct))
    return result


async def aggregate_bar_stock_pct(
    rows: Iterable[BarSupplierStockRow],
) -> dict[UUID, dict]:
    """Aggregate per-bar Σ remaining_ml / Σ dispatched_ml for the bar-card
    "Stock Level X%" indicator.

    Returns: {bar_id: {"dispatched_ml", "remaining_ml", "pct", "status"}}
    """
    by_bar: dict[UUID, dict] = {}
    for row in rows:
        slot = by_bar.setdefault(row.bar_id, {
            "bar_name": row.bar_name,
            "dispatched_ml": 0.0,
            "remaining_ml": 0.0,
        })
        slot["dispatched_ml"] += row.dispatched_ml
        slot["remaining_ml"] += row.remaining_ml

    for b_id, slot in by_bar.items():
        d = slot["dispatched_ml"]
        slot["pct"] = (slot["remaining_ml"] / d * 100.0) if d else 0.0
        slot["status"] = _resolve_status(slot["pct"], 70.0, 100.0)
    return by_bar



# ─── Auto-alert firing for depletion threshold crossings ─────────────

_STATUS_TO_SEVERITY = {
    "low":      "warning",
    "critical": "critical",
}


async def fire_depletion_alerts(
    session: AsyncSession,
    tenant_id: UUID,
    event_id: UUID,
    rows: list[BarSupplierStockRow],
) -> dict:
    """For each row with status != healthy, ensure a matching depletion
    alert exists. For each row that has returned to healthy, auto-resolve
    its active alert.

    Dedup key for depletion alerts: (bar_id, supplier_product_id) — we
    cannot use Alert.product_id because supplier_products are a separate
    table. Instead we lookup active alerts where
    context_json->>'supplier_product_id' matches.

    Idempotent: safe to call on every read; no spam — repeated calls
    update severity / version of the same active row rather than
    creating new rows.

    Returns: {"created": N, "updated": N, "resolved": N}
    """
    counts = {"created": 0, "updated": 0, "resolved": 0}

    # Fetch all active depletion alerts for this event to do the dedup
    # in Python (cheaper than 2 round-trips per row).
    active_q = await session.execute(
        select(Alert).where(
            Alert.tenant_id == tenant_id,
            Alert.event_id == event_id,
            Alert.alert_type == "depletion",
            Alert.acknowledged_at.is_(None),
            Alert.auto_resolved_at.is_(None),
            Alert.expired_at.is_(None),
        )
    )
    active_alerts = list(active_q.scalars().all())
    # Index by (bar_id, supplier_product_id_str)
    active_by_key: dict[tuple[UUID, str], Alert] = {}
    for a in active_alerts:
        sp_id_str = (a.context_json or {}).get("supplier_product_id")
        if sp_id_str is None:
            continue
        active_by_key[(a.bar_id, str(sp_id_str))] = a

    now = datetime.now(timezone.utc)

    for row in rows:
        key = (row.bar_id, str(row.supplier_product_id))
        existing = active_by_key.get(key)

        if row.status == "healthy":
            # If a previously-fired alert exists, auto-resolve it
            if existing is not None:
                existing.auto_resolved_at = now
                existing.version += 1
                counts["resolved"] += 1
            continue

        # status is 'low' or 'critical' → ensure alert exists
        target_severity = _STATUS_TO_SEVERITY[row.status]
        context = {
            "supplier_product_id":    str(row.supplier_product_id),
            "item_name":              row.item_name,
            "bar_name":               row.bar_name,
            "accurate":               row.accurate,
            "dispatched_ml":          row.dispatched_ml,
            "consumed_ml":            row.consumed_ml,
            "consumed_ml_certain":    row.consumed_ml_certain,
            "consumed_ml_uncertain":  row.consumed_ml_uncertain,
            "remaining_ml":           row.remaining_ml,
            "remaining_pct":          round(row.remaining_pct, 2),
            "threshold_pct_warn":     row.threshold_pct_warn,
            "threshold_pct_empty":    row.threshold_pct_empty,
        }
        title = (
            f"{row.item_name} {row.status} at {row.bar_name} "
            f"({int(row.remaining_pct)}% remaining)"
        )
        if row.accurate:
            owner_msg = (
                f"~{int(row.remaining_pct)}% remaining. ACCURATE reading — "
                f"{row.item_name} is the sole ingredient of its Slesh "
                f"category, so depletion math is exact. Restock now."
            )
        elif row.consumed_ml_certain > 0 and row.consumed_ml_uncertain > 0:
            owner_msg = (
                f"~{int(row.remaining_pct)}% remaining. PARTIAL accuracy: "
                f"{int(row.consumed_ml_certain)} ml certainly consumed from "
                f"sole-ingredient sales (accurate); up to "
                f"{int(row.consumed_ml_uncertain)} ml worst-case from "
                f"multi-ingredient categories where {row.item_name} is one "
                f"of several parallel options. Please verify in person."
            )
        else:
            owner_msg = (
                f"~{int(row.remaining_pct)}% remaining. WORST-CASE math: "
                f"all consumption attributed to multi-ingredient categories "
                f"({row.item_name} is one of several parallel options per "
                f"sale). Please verify the bottle in person."
            )

        if existing is not None:
            # Update severity if it escalated (low → critical) or context
            severity_changed = existing.severity != target_severity
            existing.severity = target_severity
            existing.title = title
            existing.owner_message = owner_msg
            existing.context_json = context
            existing.version += 1
            counts["updated"] += 1
            continue

        # Create new alert
        alert = Alert(
            tenant_id=tenant_id,
            event_id=event_id,
            bar_id=row.bar_id,
            product_id=None,
            alert_type="depletion",
            severity=target_severity,
            audience="owner_only",
            title=title,
            owner_message=owner_msg,
            suggested_action=f"Verify {row.item_name} bottle level at {row.bar_name}",
            context_json=context,
        )
        session.add(alert)
        counts["created"] += 1

    await session.flush()
    if any(counts.values()):
        logger.info(
            "fire_depletion_alerts event=%s: %s", event_id, counts,
        )
    return counts
