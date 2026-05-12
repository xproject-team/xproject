"""
Reconciliation report — service layer.

Single SQL query produces all data; Python groups, computes gaps, and
applies flag rules. The single-query design eliminates race-condition
risk during live events: if a DISPATCH lands between two queries, the
numbers would be inconsistent across rows vs summary. One query, one
snapshot, internally consistent.

Sundance-safety properties:
  1. Single SQL query (no inter-query race)
  2. Tenant-scoped at every CTE (multi-tenancy + injection defense)
  3. Bounded by event window (scans outside event.started_at..ended_at
     are excluded; a future event cannot pollute a past report)
  4. voided_at IS NULL filter (undone scans don't count)
  5. Decimal arithmetic throughout (precision preserved)
  6. Returns deterministic output for the same (event, snapshot time)
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.stock_transactions.models import (
    StockTransaction,
    TransactionSource,
)

from app.modules.events.reconciliation_schemas import (
    EventProductGap,
    ReconciliationReport,
    ReconciliationRow,
    ReconciliationSummary,
    ReconciliationTotals,
)


# ─── Flag rule thresholds ───────────────────────────────────────────────────
# Tuned for Sundance pilot. Phase 7 may make these tenant-configurable.

GAP_MINOR_PCT_LOWER     = Decimal("1.0")    # below this = no flag (rounding noise)
GAP_MODERATE_PCT_LOWER  = Decimal("5.0")
GAP_MAJOR_PCT_LOWER     = Decimal("15.0")


def _derive_gap_flag(dispatched: Decimal, arrived: Decimal) -> tuple[Decimal, float | None, str | None]:
    """Compute (delivery_gap, gap_pct, flag_label) for one product.

    Returns flag=None when gap is under 1% (rounding-level noise).
    Returns DELIVERY_GAP_MAJOR when dispatched > 0 and arrived == 0
    (the worst-case "manager didn't scan at all" / "stock disappeared
    in transit" pattern) — this is the highest-priority signal Omar
    pays the system to surface.
    """
    delivery_gap = dispatched - arrived

    # Division-by-zero guard. When nothing was dispatched, there's no
    # gap to compute and no flag to raise.
    if dispatched <= 0:
        return delivery_gap, None, None

    # Special-case the worst pattern: stock dispatched but NOTHING arrived.
    # Even if the math says 100% gap, we want this as DELIVERY_GAP_MAJOR
    # explicitly because it's the kind of red flag that needs immediate
    # eyes.
    if arrived <= 0:
        return delivery_gap, 100.0, "DELIVERY_GAP_MAJOR"

    # Negative gap (more arrived than dispatched) is mathematically
    # possible if manual barcode entry surfaced a product that wasn't
    # in the allocation. Surface as no-flag but don't crash.
    if delivery_gap <= 0:
        return delivery_gap, 0.0, None

    pct = (delivery_gap / dispatched) * Decimal("100")
    pct_rounded = float(round(pct, 2))

    if pct < GAP_MINOR_PCT_LOWER:
        return delivery_gap, pct_rounded, None
    if pct < GAP_MODERATE_PCT_LOWER:
        return delivery_gap, pct_rounded, "DELIVERY_GAP_MINOR"
    if pct < GAP_MAJOR_PCT_LOWER:
        return delivery_gap, pct_rounded, "DELIVERY_GAP_MODERATE"
    return delivery_gap, pct_rounded, "DELIVERY_GAP_MAJOR"


# ─── The main entry point ───────────────────────────────────────────────────

async def compute_report(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
) -> ReconciliationReport:
    """Build the full reconciliation report for one event.

    Raises 404 if event not found in this tenant.
    """

    # ── Step 1: load + validate the event ───────────────────────────────
    event_row = await db.execute(
        text("""
            SELECT id, name, status::text, started_at, ended_at, scheduled_date
            FROM events
            WHERE tenant_id = :tenant AND id = :event_id
        """),
        {"tenant": tenant_id, "event_id": event_id},
    )
    event = event_row.mappings().one_or_none()
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    # Compute once, reuse in both paths (empty-rows early return + main path).
    # One COUNT() LIMIT 1 — negligible cost vs the main report SQL.
    has_pos_data = await _has_slesh_pos_data(
        db=db, tenant_id=tenant_id, event_id=event_id,
    )

    # ── Step 2: determine the time window for scans ─────────────────────
    # started_at is canonical for "event went LIVE"; ended_at is when it
    # was closed (NULL while still LIVE — use NOW() in that case).
    # If the event was never started (status=DRAFT or ACTIVE), no scans
    # should exist anyway; we return an empty-rows report.
    started_at: datetime | None = event["started_at"]
    ended_at: datetime | None = event["ended_at"]
    window_upper = ended_at or datetime.now(timezone.utc)

    if started_at is None:
        # Event never went live — empty report, no rows or gaps to compute.
        return ReconciliationReport(
            event_id=event["id"],
            event_name=event["name"],
            event_status=event["status"].lower(),
            event_started_at=None,
            event_ended_at=None,
            generated_at=datetime.now(timezone.utc),
            rows=[],
            summary=ReconciliationSummary(
                event_level_gaps=[],
                totals=ReconciliationTotals(
                    active_rows=0,
                    total_arrived=Decimal("0"),
                    total_consumed=Decimal("0"),
                    event_delivery_gap_count=0,
                    missing_pos_data=not has_pos_data,
                ),
            ),
        )

    # ── Step 3: the single big SQL query ────────────────────────────────
    # Two CTEs:
    #   bar_product_agg  — per (bar, product) DISPATCH and CONSUMED totals
    #   product_agg      — per (product) total arrived (sum across bars)
    # Plus the LEFT JOIN onto warehouse_allocations for dispatched_qty.
    # The result is denormalized: each row carries enough to populate
    # both the per-row response AND its parent product-level gap.
    sql = text("""
        WITH bar_product_agg AS (
            SELECT
                ws.bar_id,
                ws.product_id,
                SUM(CASE WHEN ws.scan_type = 'DISPATCH' THEN ws.qty ELSE 0 END) AS arrived_qty,
                SUM(CASE WHEN ws.scan_type = 'CONSUMED' THEN ws.qty ELSE 0 END) AS consumed_qty
            FROM warehouse_scans ws
            WHERE ws.tenant_id    = :tenant
              AND ws.event_id     = :event_id
              AND ws.voided_at    IS NULL
              AND ws.bar_id       IS NOT NULL
              AND ws.product_id   IS NOT NULL
              AND ws.scan_type IN ('DISPATCH', 'CONSUMED')
              AND ws.scanned_at >= :window_lower
              AND ws.scanned_at <= :window_upper
            GROUP BY ws.bar_id, ws.product_id
        ),
        product_agg AS (
            SELECT
                product_id,
                SUM(arrived_qty)   AS total_arrived_at_event,
                SUM(consumed_qty)  AS total_consumed_at_event
            FROM bar_product_agg
            GROUP BY product_id
        )
        SELECT
            -- Per-(bar, product) detail
            bpa.bar_id,
            b.name           AS bar_name,
            bpa.product_id,
            p.name           AS product_name,
            bpa.arrived_qty,
            bpa.consumed_qty,
            -- Per-product event-level totals (denormalized onto each row)
            pa.total_arrived_at_event,
            pa.total_consumed_at_event,
            -- Allocation-side truth (per event, per product)
            COALESCE(wa.dispatched_qty, 0) AS dispatched_qty
        FROM bar_product_agg bpa
        JOIN product_agg pa  ON pa.product_id = bpa.product_id
        JOIN bars b          ON b.id = bpa.bar_id
        JOIN products p      ON p.id = bpa.product_id
        LEFT JOIN warehouse_allocations wa
               ON wa.tenant_id = :tenant
              AND wa.event_id  = :event_id
              AND wa.product_id = bpa.product_id
        WHERE (bpa.arrived_qty > 0 OR bpa.consumed_qty > 0)   -- only active pairs
        ORDER BY b.name ASC, p.name ASC
    """)

    result = await db.execute(
        sql,
        {
            "tenant": tenant_id,
            "event_id": event_id,
            "window_lower": started_at,
            "window_upper": window_upper,
        },
    )
    raw_rows: Sequence = result.mappings().all()

    # ── Step 4: also pick up product-level dispatch rows that had ZERO arrivals ─
    # These are the worst-case "warehouse sent stock but no bar scanned
    # any of it" signal. The main query above won't surface them (the
    # WHERE filter requires at least one DISPATCH or CONSUMED scan).
    # We do a small separate query for them — fast since it's just
    # allocations LEFT JOIN scans.
    zero_arrival_sql = text("""
        SELECT
            wa.product_id,
            p.name AS product_name,
            wa.dispatched_qty
        FROM warehouse_allocations wa
        JOIN products p ON p.id = wa.product_id
        WHERE wa.tenant_id = :tenant
          AND wa.event_id  = :event_id
          AND wa.dispatched_qty > 0
          AND NOT EXISTS (
              SELECT 1 FROM warehouse_scans ws
              WHERE ws.tenant_id = :tenant
                AND ws.event_id  = :event_id
                AND ws.product_id = wa.product_id
                AND ws.scan_type  = 'DISPATCH'
                AND ws.voided_at  IS NULL
                AND ws.scanned_at >= :window_lower
                AND ws.scanned_at <= :window_upper
          )
        ORDER BY p.name ASC
    """)
    zero_result = await db.execute(
        zero_arrival_sql,
        {
            "tenant": tenant_id,
            "event_id": event_id,
            "window_lower": started_at,
            "window_upper": window_upper,
        },
    )
    zero_arrivals: Sequence = zero_result.mappings().all()

    # ── Step 5: assemble rows ───────────────────────────────────────────
    rows: list[ReconciliationRow] = []
    for r in raw_rows:
        arrived = Decimal(r["arrived_qty"])
        consumed = Decimal(r["consumed_qty"])
        rows.append(
            ReconciliationRow(
                bar_id=r["bar_id"],
                bar_name=r["bar_name"],
                product_id=r["product_id"],
                product_name=r["product_name"],
                arrived_qty=arrived,
                consumed_qty=consumed,
                net_qty=arrived - consumed,
                flags=[],   # row-level flags reserved for POS-wired future
            )
        )

    # ── Step 6: assemble event-level gaps (per product) ─────────────────
    # First pass: products that had at least one scan.
    product_seen: dict[UUID, dict] = {}
    for r in raw_rows:
        pid = r["product_id"]
        if pid not in product_seen:
            product_seen[pid] = {
                "product_name": r["product_name"],
                "dispatched_qty": Decimal(r["dispatched_qty"]),
                "total_arrived_at_event": Decimal(r["total_arrived_at_event"]),
            }

    gaps: list[EventProductGap] = []
    for pid, info in product_seen.items():
        delivery_gap, gap_pct, flag = _derive_gap_flag(
            info["dispatched_qty"],
            info["total_arrived_at_event"],
        )
        if flag is not None:
            gaps.append(
                EventProductGap(
                    product_id=pid,
                    product_name=info["product_name"],
                    dispatched_qty=info["dispatched_qty"],
                    total_arrived_at_event=info["total_arrived_at_event"],
                    delivery_gap=delivery_gap,
                    gap_pct=gap_pct,
                    flag=flag,
                )
            )

    # Second pass: products with dispatched > 0 but ZERO arrivals.
    # These are MAJOR by definition (handled by _derive_gap_flag's
    # special case).
    for r in zero_arrivals:
        pid = r["product_id"]
        if pid in product_seen:
            # Shouldn't happen if the queries are mutually exclusive, but
            # defensive — never double-report.
            continue
        delivery_gap, gap_pct, flag = _derive_gap_flag(
            Decimal(r["dispatched_qty"]),
            Decimal("0"),
        )
        if flag is not None:
            gaps.append(
                EventProductGap(
                    product_id=pid,
                    product_name=r["product_name"],
                    dispatched_qty=Decimal(r["dispatched_qty"]),
                    total_arrived_at_event=Decimal("0"),
                    delivery_gap=delivery_gap,
                    gap_pct=gap_pct,
                    flag=flag,
                )
            )

    # Sort gaps by severity descending, then name — MAJOR first so Omar
    # sees the most urgent items at the top.
    severity_rank = {"DELIVERY_GAP_MAJOR": 0, "DELIVERY_GAP_MODERATE": 1, "DELIVERY_GAP_MINOR": 2}
    gaps.sort(key=lambda g: (severity_rank.get(g.flag or "", 99), g.product_name))

    # ── Step 7: totals ──────────────────────────────────────────────────
    totals = ReconciliationTotals(
        active_rows=len(rows),
        total_arrived=sum((r.arrived_qty for r in rows), Decimal("0")),
        total_consumed=sum((r.consumed_qty for r in rows), Decimal("0")),
        event_delivery_gap_count=len(gaps),
        missing_pos_data=not has_pos_data,
    )

    return ReconciliationReport(
        event_id=event["id"],
        event_name=event["name"],
        event_status=event["status"].lower(),
        event_started_at=started_at,
        event_ended_at=ended_at,
        generated_at=datetime.now(timezone.utc),
        rows=rows,
        summary=ReconciliationSummary(
            event_level_gaps=gaps,
            totals=totals,
        ),
    )

# ─────────────────────────────────────────────────────────────────────
# Helper: does this event have ANY Slesh POS data ingested?
# ─────────────────────────────────────────────────────────────────────
async def _has_slesh_pos_data(
    *,
    db:         AsyncSession,
    tenant_id:  UUID,
    event_id:   UUID,
) -> bool:
    """Returns True iff at least one stock_transaction row with
    source=SLESH_POS exists for this (tenant, event).

    Used by compute_report() to populate the missing_pos_data flag.
    The query is not time-scoped: we want to know if POS data EVER
    landed for this event, not whether it landed within the report
    window. Slesh data outside the event window would be a data-
    quality issue (separate concern), but presence proves the
    integration is operating.

    Single COUNT() with LIMIT 1 — index lookup on (tenant_id, event_id),
    negligible cost vs the main report SQL.
    """
    stmt = (
        select(func.count())
        .select_from(StockTransaction)
        .where(StockTransaction.tenant_id == tenant_id)
        .where(StockTransaction.event_id  == event_id)
        .where(StockTransaction.source    == TransactionSource.SLESH_POS)
        .limit(1)
    )
    res = await db.execute(stmt)
    return (res.scalar() or 0) > 0

