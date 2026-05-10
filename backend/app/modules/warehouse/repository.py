"""Database queries for the Warehouse module — pure data access, no business logic.

This file owns ALL SQL for the warehouse domain. Services never write SQL.
Transaction boundaries are OWNED BY SERVICES — every method here flushes
but NEVER commits.

Five repository classes, one per table. Split keeps each class focused:
  InvoiceRepository          — delivery_invoices + invoice_items
  InventoryRepository        — warehouse_inventory
  ScanRepository             — warehouse_scans (append-only audit trail)
  AllocationRepository       — warehouse_allocations

Spec: docs/warehouse-module-spec.md §4 + §5.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence
from uuid import UUID

from sqlalchemy import and_, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.events.models import Event, EventStatus
from app.modules.products.models import Product
from app.modules.warehouse.models import (
    DeliveryInvoice,
    InvoiceItem,
    WarehouseAllocation,
    WarehouseInventory,
    WarehouseScan,
)

# Event statuses that keep allocations "live" — used by active_allocations KPI
# and by over-allocation prevention. Completed events don't hold reservations.
_LIVE_EVENT_STATUSES = (
    EventStatus.DRAFT,
    EventStatus.LIVE,
)


# ═════════════════════════════════════════════════════════════════════════════
# InvoiceRepository
# ═════════════════════════════════════════════════════════════════════════════

class InvoiceRepository:
    """SQL for delivery_invoices + invoice_items.

    Tenant isolation on every public method. A missing tenant_id filter
    is a security bug; reviewers should fail the PR.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Reads ────────────────────────────────────────────────────────────────

    async def get_by_id(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
    ) -> DeliveryInvoice | None:
        """Fetch a single invoice with its items pre-loaded.

        Eager-loads items via the back_populates relationship.
        Returns None if not found OR belongs to a different tenant.
        """
        stmt = (
            select(DeliveryInvoice)
            .options(selectinload(DeliveryInvoice.items))
            .where(
                DeliveryInvoice.tenant_id == tenant_id,
                DeliveryInvoice.id == invoice_id,
            )
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_for_tenant(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> Sequence[DeliveryInvoice]:
        """List invoices, newest first.

        When `status` is given, filters to that status (e.g. 'EXPECTED' for
        the pending-deliveries dashboard strip). Includes items for summary
        rendering but uses the standard back_populates eager-load.
        """
        stmt = (
            select(DeliveryInvoice)
            .options(selectinload(DeliveryInvoice.items))
            .where(DeliveryInvoice.tenant_id == tenant_id)
            .order_by(desc(DeliveryInvoice.expected_arrival_date))
            .limit(limit)
        )
        if status is not None:
            stmt = stmt.where(DeliveryInvoice.status == status)

        return (await self.db.execute(stmt)).scalars().all()

    async def list_pending_deliveries(
        self,
        tenant_id: UUID,
    ) -> Sequence[DeliveryInvoice]:
        """Dashboard strip: invoices in EXPECTED/SCANNING/PAUSED states.

        Sorted by expected_arrival_date ASC so the soonest-arriving trucks
        float to the top.
        """
        stmt = (
            select(DeliveryInvoice)
            .options(selectinload(DeliveryInvoice.items))
            .where(
                DeliveryInvoice.tenant_id == tenant_id,
                DeliveryInvoice.status.in_(("EXPECTED", "SCANNING", "PAUSED")),
            )
            .order_by(DeliveryInvoice.expected_arrival_date.asc())
        )
        return (await self.db.execute(stmt)).scalars().all()

    # ─── Writes ───────────────────────────────────────────────────────────────

    async def create(
        self,
        tenant_id: UUID,
        *,
        invoice_number: str | None,
        supplier_name: str,
        expected_arrival_date,
        notes: str | None,
    ) -> DeliveryInvoice:
        """Create a new invoice row with status=EXPECTED (server default).

        Line items are inserted separately via `add_item()` — keeps the
        method signature small and allows flexible item construction.
        Flushes to get the id; does NOT commit.
        """
        invoice = DeliveryInvoice(
            tenant_id=tenant_id,
            invoice_number=invoice_number,
            supplier_name=supplier_name,
            expected_arrival_date=expected_arrival_date,
            notes=notes,
        )
        self.db.add(invoice)
        await self.db.flush()
        await self.db.refresh(invoice)
        return invoice

    async def add_item(
        self,
        *,
        tenant_id: UUID,
        invoice_id: UUID,
        kind: str,
        product_id: UUID | None,
        miscellaneous_description: str | None,
        expected_qty: Decimal,
        unit_price_cents: int | None,
    ) -> InvoiceItem:
        """Add one line item to an existing invoice.

        Caller is responsible for correctness (kind matches product_id/description).
        The DB-level CHECK constraints will reject inconsistent rows, but we
        raise cleaner errors in the service layer before this point.

        line_total_cents is auto-computed when both expected_qty + unit_price_cents
        are provided. Otherwise left NULL.
        """
        line_total = None
        if unit_price_cents is not None:
            # qty is Decimal, unit_price is int cents — compute in cents
            line_total = int(expected_qty * Decimal(unit_price_cents))

        item = InvoiceItem(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            kind=kind,
            product_id=product_id,
            miscellaneous_description=miscellaneous_description,
            expected_qty=expected_qty,
            unit_price_cents=unit_price_cents,
            line_total_cents=line_total,
        )
        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def update_status(
        self,
        invoice: DeliveryInvoice,
        new_status: str,
        *,
        scan_started_at: datetime | None = None,
        scan_closed_at: datetime | None = None,
        closed_by: UUID | None = None,
    ) -> DeliveryInvoice:
        """Transition an invoice to a new state.

        The caller (InvoiceService) validates the transition is legal per
        the spec §5 state machine. This method just writes.
        """
        invoice.status = new_status
        if scan_started_at is not None:
            invoice.scan_started_at = scan_started_at
        if scan_closed_at is not None:
            invoice.scan_closed_at = scan_closed_at
        if closed_by is not None:
            invoice.closed_by = closed_by
        await self.db.flush()
        await self.db.refresh(invoice)
        return invoice

    async def update_fields(
        self,
        invoice: DeliveryInvoice,
        updates: dict,
    ) -> DeliveryInvoice:
        """Edit invoice header fields (while status=EXPECTED only — service enforces)."""
        for field, value in updates.items():
            setattr(invoice, field, value)
        await self.db.flush()
        await self.db.refresh(invoice)
        return invoice


# ═════════════════════════════════════════════════════════════════════════════
# InventoryRepository
# ═════════════════════════════════════════════════════════════════════════════

class InventoryRepository:
    """SQL for warehouse_inventory — tenant-scoped product stock."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Reads ────────────────────────────────────────────────────────────────

    async def get_by_product(
        self,
        tenant_id: UUID,
        product_id: UUID,
    ) -> WarehouseInventory | None:
        """Get the single row for one product, or None if no stock tracked yet."""
        stmt = select(WarehouseInventory).where(
            WarehouseInventory.tenant_id == tenant_id,
            WarehouseInventory.product_id == product_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_grid(
        self,
        tenant_id: UUID,
    ) -> Sequence[tuple[WarehouseInventory, Product, Decimal]]:
        """Product grid view: inventory row + product metadata + sum of live allocations.

        Returns tuples of (inventory_row, product_row, allocated_qty) so the
        service layer can assemble InventoryRow responses without N+1 queries.

        Allocated qty sums (reserved - dispatched) across events that are still
        live — completed events have no lingering reservation.
        """
        allocation_subquery = (
            select(
                WarehouseAllocation.product_id.label("p_id"),
                func.coalesce(
                    func.sum(
                        WarehouseAllocation.reserved_qty
                        - WarehouseAllocation.dispatched_qty
                    ),
                    0,
                ).label("allocated"),
            )
            .join(
                Event,
                and_(
                    Event.id == WarehouseAllocation.event_id,
                    Event.tenant_id == tenant_id,
                    Event.status.in_(_LIVE_EVENT_STATUSES),
                ),
            )
            .where(WarehouseAllocation.tenant_id == tenant_id)
            .group_by(WarehouseAllocation.product_id)
            .subquery()
        )

        stmt = (
            select(
                WarehouseInventory,
                Product,
                func.coalesce(allocation_subquery.c.allocated, 0).label(
                    "allocated_qty"
                ),
            )
            .join(Product, Product.id == WarehouseInventory.product_id)
            .outerjoin(
                allocation_subquery,
                allocation_subquery.c.p_id == WarehouseInventory.product_id,
            )
            .where(WarehouseInventory.tenant_id == tenant_id)
            .order_by(Product.name.asc())
        )
        rows = (await self.db.execute(stmt)).all()
        # rows is a sequence of Row objects; unpack into tuples
        return [(r[0], r[1], Decimal(r[2])) for r in rows]

    async def count_total_items(self, tenant_id: UUID) -> int:
        """KPI tile #1: distinct products with current_qty > 0."""
        stmt = select(func.count(WarehouseInventory.id)).where(
            WarehouseInventory.tenant_id == tenant_id,
            WarehouseInventory.current_qty > 0,
        )
        return (await self.db.execute(stmt)).scalar_one() or 0

    async def sum_total_quantity(self, tenant_id: UUID) -> Decimal:
        """Sum of all current_qty across all products."""
        stmt = select(
            func.coalesce(func.sum(WarehouseInventory.current_qty), 0)
        ).where(WarehouseInventory.tenant_id == tenant_id)
        result = (await self.db.execute(stmt)).scalar_one() or 0
        return Decimal(result)

    async def count_at_risk(self, tenant_id: UUID) -> int:
        """KPI tile #2: products where current_qty < threshold.

        Uses the product-specific threshold when set, else the default 10.
        """
        threshold_default = Decimal("10")
        threshold_expr = func.coalesce(
            WarehouseInventory.low_stock_threshold, threshold_default
        )
        stmt = select(func.count(WarehouseInventory.id)).where(
            WarehouseInventory.tenant_id == tenant_id,
            WarehouseInventory.current_qty < threshold_expr,
        )
        return (await self.db.execute(stmt)).scalar_one() or 0

    # ─── Writes ───────────────────────────────────────────────────────────────

    async def upsert_delta(
        self,
        tenant_id: UUID,
        product_id: UUID,
        delta: Decimal,
    ) -> WarehouseInventory:
        """Apply a stock delta (+ or -) to a product's inventory row.

        Creates the row if it doesn't exist (starts at 0, then applies delta).
        Sets last_movement_at to now. Does NOT commit.

        Service layer is responsible for:
          - Validating delta direction matches the scan_type (INTAKE=+, etc.)
          - Ensuring the resulting qty won't go negative (DB CHECK will fail loudly)
        """
        row = await self.get_by_product(tenant_id, product_id)
        now = datetime.now(timezone.utc)

        if row is None:
            row = WarehouseInventory(
                tenant_id=tenant_id,
                product_id=product_id,
                current_qty=max(Decimal(0), delta),
                last_movement_at=now,
            )
            self.db.add(row)
        else:
            row.current_qty = row.current_qty + delta
            row.last_movement_at = now

        await self.db.flush()
        await self.db.refresh(row)
        return row


# ═════════════════════════════════════════════════════════════════════════════
# ScanRepository
# ═════════════════════════════════════════════════════════════════════════════

class ScanRepository:
    """SQL for warehouse_scans — append-only audit trail."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Reads ────────────────────────────────────────────────────────────────

    async def get_by_id(
        self,
        tenant_id: UUID,
        scan_id: UUID,
    ) -> WarehouseScan | None:
        stmt = select(WarehouseScan).where(
            WarehouseScan.tenant_id == tenant_id,
            WarehouseScan.id == scan_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def find_by_client_event_id(
        self,
        tenant_id: UUID,
        client_event_id: UUID,
    ) -> WarehouseScan | None:
        """Idempotency lookup. Used by submit_scan to dedupe retries.

        Returns the existing scan with product/bar/scanned_by relationships
        eagerly loaded so router serialization does not trip greenlet
        checks. The unique partial index on (tenant_id, client_event_id)
        makes this an index-only lookup.
        """
        stmt = (
            select(WarehouseScan)
            .options(
                selectinload(WarehouseScan.product),
                selectinload(WarehouseScan.bar),
                selectinload(WarehouseScan.scanned_by),
            )
            .where(
                WarehouseScan.tenant_id == tenant_id,
                WarehouseScan.client_event_id == client_event_id,
            )
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_id_with_relationships(
        self,
        tenant_id: UUID,
        scan_id: UUID,
    ) -> WarehouseScan | None:
        """Same as get_by_id but eager-loads product/bar/scanned_by so the
        ORM object is safe to hand to the response serializer. Used by
        submit_scan to re-fetch the row it just created.
        """
        stmt = (
            select(WarehouseScan)
            .options(
                selectinload(WarehouseScan.product),
                selectinload(WarehouseScan.bar),
                selectinload(WarehouseScan.scanned_by),
            )
            .where(
                WarehouseScan.tenant_id == tenant_id,
                WarehouseScan.id == scan_id,
            )
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_activity_feed(
        self,
        tenant_id: UUID,
        limit: int = 20,
    ) -> Sequence[WarehouseScan]:
        """Dashboard side panel: most recent scans, newest first."""
        stmt = (
            select(WarehouseScan)
            .options(
                selectinload(WarehouseScan.product),
                selectinload(WarehouseScan.scanned_by),
            )
            .where(WarehouseScan.tenant_id == tenant_id)
            .order_by(desc(WarehouseScan.scanned_at))
            .limit(limit)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def list_for_invoice(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
    ) -> Sequence[WarehouseScan]:
        """All scans for one invoice session — used for reconciliation."""
        stmt = (
            select(WarehouseScan)
            .options(selectinload(WarehouseScan.product))
            .where(
                WarehouseScan.tenant_id == tenant_id,
                WarehouseScan.invoice_id == invoice_id,
            )
            .order_by(WarehouseScan.scanned_at.asc())
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def list_pending_review(
        self,
        tenant_id: UUID,
    ) -> Sequence[WarehouseScan]:
        """Owner's pending-review queue.

        Uses the partial index on (tenant_id, scanned_at) WHERE pending_review=true
        declared in the migration — this query is fast even with millions of scans.
        """
        stmt = (
            select(WarehouseScan)
            .options(
                selectinload(WarehouseScan.product),
                selectinload(WarehouseScan.scanned_by),
                selectinload(WarehouseScan.invoice),
            )
            .where(
                WarehouseScan.tenant_id == tenant_id,
                WarehouseScan.pending_review.is_(True),
            )
            .order_by(desc(WarehouseScan.scanned_at))
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def count_pending_review(self, tenant_id: UUID) -> int:
        """KPI tile #4 component: count of scans awaiting Owner review."""
        stmt = select(func.count(WarehouseScan.id)).where(
            WarehouseScan.tenant_id == tenant_id,
            WarehouseScan.pending_review.is_(True),
        )
        return (await self.db.execute(stmt)).scalar_one() or 0

    # ─── Writes ───────────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        tenant_id: UUID,
        scan_type: str,
        scanned_by_role: str,
        qty: Decimal,
        product_id: UUID | None = None,
        barcode_raw: str | None = None,
        invoice_id: UUID | None = None,
        event_id: UUID | None = None,
        bar_id: UUID | None = None,
        is_unexpected: bool = False,
        pending_review: bool = False,
        scanned_by_user_id: UUID | None = None,
        client_event_id: UUID | None = None,
    ) -> WarehouseScan:
        """Append a scan row. The hot write path.

        scanned_at defaults to now() via DB default. Nothing on this row is
        updatable after insert EXCEPT pending_review (flipped on Owner action).
        """
        scan = WarehouseScan(
            tenant_id=tenant_id,
            scan_type=scan_type,
            scanned_by_role=scanned_by_role,
            qty=qty,
            product_id=product_id,
            barcode_raw=barcode_raw,
            invoice_id=invoice_id,
            event_id=event_id,
            bar_id=bar_id,
            is_unexpected=is_unexpected,
            pending_review=pending_review,
            scanned_by_user_id=scanned_by_user_id,
            client_event_id=client_event_id,
            scanned_at=datetime.now(timezone.utc),
        )
        self.db.add(scan)
        await self.db.flush()
        await self.db.refresh(scan)
        return scan

    async def clear_pending_review(self, scan: WarehouseScan) -> WarehouseScan:
        """Owner approved or rejected — flip the flag."""
        scan.pending_review = False
        await self.db.flush()
        await self.db.refresh(scan)
        return scan


# ═════════════════════════════════════════════════════════════════════════════
# AllocationRepository
# ═════════════════════════════════════════════════════════════════════════════

class AllocationRepository:
    """SQL for warehouse_allocations — event reservations against warehouse stock."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Reads ────────────────────────────────────────────────────────────────

    async def get_by_event_product(
        self,
        tenant_id: UUID,
        event_id: UUID,
        product_id: UUID,
    ) -> WarehouseAllocation | None:
        stmt = select(WarehouseAllocation).where(
            WarehouseAllocation.tenant_id == tenant_id,
            WarehouseAllocation.event_id == event_id,
            WarehouseAllocation.product_id == product_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> Sequence[tuple[WarehouseAllocation, Product]]:
        """All allocations for one event, joined with product names."""
        stmt = (
            select(WarehouseAllocation, Product)
            .join(Product, Product.id == WarehouseAllocation.product_id)
            .where(
                WarehouseAllocation.tenant_id == tenant_id,
                WarehouseAllocation.event_id == event_id,
            )
            .order_by(Product.name.asc())
        )
        rows = (await self.db.execute(stmt)).all()
        return [(r[0], r[1]) for r in rows]

    async def sum_active_reservations(
        self,
        tenant_id: UUID,
    ) -> Decimal:
        """KPI tile #3: total reserved qty across live/upcoming events.

        Only counts events in DRAFT or LIVE status — completed events don't
        hold reservations anymore.
        """
        stmt = (
            select(
                func.coalesce(func.sum(WarehouseAllocation.reserved_qty), 0)
            )
            .join(
                Event,
                and_(
                    Event.id == WarehouseAllocation.event_id,
                    Event.tenant_id == tenant_id,
                    Event.status.in_(_LIVE_EVENT_STATUSES),
                ),
            )
            .where(WarehouseAllocation.tenant_id == tenant_id)
        )
        result = (await self.db.execute(stmt)).scalar_one() or 0
        return Decimal(result)

    # ─── Writes ───────────────────────────────────────────────────────────────

    async def upsert_reservation(
        self,
        tenant_id: UUID,
        event_id: UUID,
        product_id: UUID,
        reserved_qty: Decimal,
    ) -> WarehouseAllocation:
        """Set the reserved_qty for (event, product). Creates the row if missing.

        Leaves dispatched_qty unchanged. The DB CHECK will reject reservations
        below current dispatched_qty, so the service layer must validate.
        """
        existing = await self.get_by_event_product(tenant_id, event_id, product_id)
        if existing is None:
            row = WarehouseAllocation(
                tenant_id=tenant_id,
                event_id=event_id,
                product_id=product_id,
                reserved_qty=reserved_qty,
                dispatched_qty=Decimal(0),
            )
            self.db.add(row)
        else:
            existing.reserved_qty = reserved_qty
            row = existing

        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def increment_dispatched(
        self,
        allocation: WarehouseAllocation,
        delta: Decimal,
    ) -> WarehouseAllocation:
        """Physical DISPATCH scan happened; bump dispatched_qty.

        DB CHECK will reject if dispatched_qty would exceed reserved_qty.
        Service layer should pre-validate to give a cleaner error.
        """
        allocation.dispatched_qty = allocation.dispatched_qty + delta
        await self.db.flush()
        await self.db.refresh(allocation)
        return allocation
