"""SQLAlchemy ORM models for the Warehouse module.

Five tables, one file — all warehouse entities are tightly coupled and live
together for clarity. Mirrors the migration j1_add_warehouse.py exactly.

Tables (in order of declaration):
  DeliveryInvoice         — hero entity, invoice lifecycle anchor
  InvoiceItem             — line items (catalog OR miscellaneous freetext)
  WarehouseInventory      — tenant-scoped product stock
  WarehouseScan           — append-only audit trail with role snapshots
  WarehouseAllocation     — events reserving stock from warehouse

All inherit from TenantScopedModel per codebase convention
(id UUID PK, tenant_id FK CASCADE, created_at, updated_at auto-managed).

Spec: docs/warehouse-module-spec.md §4.
Migration: backend/alembic/versions/j1_add_warehouse.py.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Enum as SqlEnum,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import relationship

from app.core.tenancy import TenantScopedModel


# ─── Enum types (native Postgres, declared in migration) ──────────────────────
# create_type=False because enums are created by the migration directly.

INVOICE_STATUS_ENUM = SqlEnum(
    "EXPECTED",
    "SCANNING",
    "PAUSED",
    "VERIFIED",
    "DISCREPANCY",
    "DISPUTED",
    "CLOSED",
    name="invoicestatus",
    create_type=False,
)
SCAN_TYPE_ENUM = SqlEnum(
    "INTAKE",
    "DISPATCH",
    "RETURN",
    "ADJUSTMENT",
    "INSPECT",
    "CONSUMED",
    name="scantype",
    create_type=False,
)
SCANNER_ROLE_ENUM = SqlEnum(
    "owner",
    "manager",
    "bartender",
    "warehouse_keeper",
    name="scannerrole",
    create_type=False,
)
INVOICE_LINE_KIND_ENUM = SqlEnum(
    "catalog_product",
    "miscellaneous",
    name="invoicelinekind",
    create_type=False,
)


# ═════════════════════════════════════════════════════════════════════════════
# DeliveryInvoice — the hero entity
# ═════════════════════════════════════════════════════════════════════════════

class DeliveryInvoice(TenantScopedModel):
    """One delivery invoice from a supplier.

    Created by Owner BEFORE truck arrives (status=EXPECTED). As staff scan
    the delivery, it transitions through SCANNING/PAUSED. On close, the
    reconciliation engine compares expected vs scanned and sets final
    status to VERIFIED / DISCREPANCY / DISPUTED, then eventually CLOSED.

    Full state machine in docs/warehouse-module-spec.md §5.
    """

    __tablename__ = "delivery_invoices"

    invoice_number = Column(String(128), nullable=True)
    # supplier_name is freetext varchar(255) per spec §4.X — supplier modeling
    # deferred pending Omar's invoice sample. Future v1.1 migration may add
    # supplier_id FK and backfill from distinct values of this column.
    supplier_name = Column(String(255), nullable=False)
    expected_arrival_date = Column(Date, nullable=False)
    status = Column(INVOICE_STATUS_ENUM, nullable=False, default="EXPECTED")
    scan_started_at = Column(DateTime(timezone=True), nullable=True)
    scan_closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by = Column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes = Column(Text, nullable=True)

    # Relationships
    items = relationship(
        "InvoiceItem",
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    scans = relationship(
        "WarehouseScan",
        back_populates="invoice",
        lazy="noload",  # Only fetched when explicitly requested — scan volume can be high
    )
    closed_by_user = relationship("User", foreign_keys=[closed_by])

    __table_args__ = (
        Index("ix_delivery_invoices_tenant_id", "tenant_id"),
        Index("ix_delivery_invoices_tenant_status", "tenant_id", "status"),
        Index(
            "ix_delivery_invoices_tenant_arrival_date",
            "tenant_id",
            "expected_arrival_date",
        ),
        Index(
            "ix_delivery_invoices_tenant_supplier",
            "tenant_id",
            "supplier_name",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<DeliveryInvoice {self.id} "
            f"{self.supplier_name!r} {self.status}>"
        )


# ═════════════════════════════════════════════════════════════════════════════
# InvoiceItem — line items (catalog product OR miscellaneous freetext)
# ═════════════════════════════════════════════════════════════════════════════

class InvoiceItem(TenantScopedModel):
    """One expected line item on an invoice.

    Two shapes, enforced by CHECK constraints in the migration:
      kind='catalog_product' → product_id required, miscellaneous_description NULL
      kind='miscellaneous'   → miscellaneous_description required, product_id NULL

    unit_price_cents is optional. line_total_cents is computed by the service
    layer on insert/update from qty * unit_price_cents when both exist.
    """

    __tablename__ = "invoice_items"

    invoice_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("delivery_invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = Column(
        INVOICE_LINE_KIND_ENUM,
        nullable=False,
        default="catalog_product",
    )
    product_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=True,
    )
    miscellaneous_description = Column(String(255), nullable=True)
    expected_qty = Column(Numeric(12, 2), nullable=False)
    unit_price_cents = Column(Integer, nullable=True)
    line_total_cents = Column(Integer, nullable=True)

    # Relationships
    invoice = relationship("DeliveryInvoice", back_populates="items")
    product = relationship("Product", foreign_keys=[product_id])

    __table_args__ = (
        CheckConstraint(
            "(kind = 'catalog_product' AND product_id IS NOT NULL) OR "
            "(kind = 'miscellaneous' AND miscellaneous_description IS NOT NULL)",
            name="ck_invoice_items_has_description",
        ),
        CheckConstraint(
            "(kind = 'catalog_product' AND miscellaneous_description IS NULL) OR "
            "(kind = 'miscellaneous' AND product_id IS NULL)",
            name="ck_invoice_items_kind_consistency",
        ),
        Index("ix_invoice_items_tenant_id", "tenant_id"),
        Index("ix_invoice_items_invoice_id", "invoice_id"),
        Index("ix_invoice_items_tenant_product", "tenant_id", "product_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<InvoiceItem {self.id} invoice={self.invoice_id} "
            f"kind={self.kind} qty={self.expected_qty}>"
        )


# ═════════════════════════════════════════════════════════════════════════════
# WarehouseInventory — tenant-scoped per-product stock
# ═════════════════════════════════════════════════════════════════════════════

class WarehouseInventory(TenantScopedModel):
    """Current stock of one product in the tenant's warehouse.

    Per spec §4.3: NOT event-scoped. Warehouse has its own inventory
    independent of which events might use it. Events allocate via
    WarehouseAllocation.

    Unique constraint (tenant_id, product_id) means one row per product.
    Updates happen via ScanService — every INTAKE/RETURN/ADJUSTMENT mutates
    current_qty and bumps last_movement_at.
    """

    __tablename__ = "warehouse_inventory"

    product_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    current_qty = Column(Numeric(12, 2), nullable=False, default=0)
    low_stock_threshold = Column(Numeric(12, 2), nullable=True)
    last_movement_at = Column(DateTime(timezone=True), nullable=True)

    product = relationship("Product", foreign_keys=[product_id])

    __table_args__ = (
        CheckConstraint(
            "current_qty >= 0",
            name="ck_warehouse_inventory_nonneg",
        ),
        Index("ix_warehouse_inventory_tenant_id", "tenant_id"),
        Index(
            "ix_warehouse_inventory_tenant_product",
            "tenant_id",
            "product_id",
            unique=True,
        ),
        Index(
            "ix_warehouse_inventory_tenant_low",
            "tenant_id",
            "current_qty",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<WarehouseInventory product={self.product_id} "
            f"qty={self.current_qty}>"
        )


# ═════════════════════════════════════════════════════════════════════════════
# WarehouseScan — append-only audit trail
# ═════════════════════════════════════════════════════════════════════════════

class WarehouseScan(TenantScopedModel):
    """One scan event. Append-only; rows never updated except for
    pending_review flag (flipped when Owner approves/rejects an unexpected scan).

    scanned_by_role is a snapshot at scan time — even if Marco gets promoted
    from warehouse_keeper to manager next week, his Monday scans still show
    'warehouse_keeper'. Preserves historical truth.

    Different scan_types use different FK subsets (enforced in service layer):
      INTAKE        → invoice_id set; event_id, bar_id NULL
      DISPATCH      → event_id + bar_id set; invoice_id NULL
      RETURN        → event_id + bar_id set; invoice_id NULL
      CONSUMED      → event_id + bar_id set; invoice_id NULL
      INSPECT       → all context optional; no DB state change beyond the scan log
      ADJUSTMENT    → freeform Owner correction
    """

    __tablename__ = "warehouse_scans"

    scan_type = Column(SCAN_TYPE_ENUM, nullable=False)
    invoice_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("delivery_invoices.id", ondelete="SET NULL"),
        nullable=True,
    )
    product_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )
    barcode_raw = Column(String(255), nullable=True)
    qty = Column(Numeric(12, 2), nullable=False, default=1)
    event_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
    )
    bar_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("bars.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_unexpected = Column(Boolean, nullable=False, default=False)
    pending_review = Column(Boolean, nullable=False, default=False)
    scanned_by_user_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # scanned_by_role is a SNAPSHOT — never update after insert
    scanned_by_role = Column(SCANNER_ROLE_ENUM, nullable=False)
    scanned_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=None,  # Migration default is now(); Python default handled server-side
    )

    # Idempotency key — UUID generated client-side at scan-event time.
    # Server dedupes by (tenant_id, client_event_id) via partial unique index.
    # NULL allowed for backward compatibility with pre-Step-6.3 clients
    # and for legacy rows; new client code always sends one.
    client_event_id = Column(
        PgUUID(as_uuid=True),
        nullable=True,
    )

    # Relationships
    invoice = relationship("DeliveryInvoice", back_populates="scans", foreign_keys=[invoice_id])
    product = relationship("Product", foreign_keys=[product_id])
    event = relationship("Event", foreign_keys=[event_id])
    bar = relationship("Bar", foreign_keys=[bar_id])
    scanned_by = relationship("User", foreign_keys=[scanned_by_user_id])

    __table_args__ = (
        CheckConstraint(
            "qty > 0",
            name="ck_warehouse_scans_qty_positive",
        ),
        Index("ix_warehouse_scans_tenant_id", "tenant_id"),
        Index("ix_warehouse_scans_tenant_at", "tenant_id", "scanned_at"),
        Index("ix_warehouse_scans_tenant_invoice", "tenant_id", "invoice_id"),
        Index(
            "ix_warehouse_scans_tenant_event_bar",
            "tenant_id",
            "event_id",
            "bar_id",
        ),
        # Partial index declared in migration (pending_review=true only).
        # SQLAlchemy declares it WITHOUT the WHERE clause to avoid autogenerate
        # drift; the migration is the source of truth for the partial predicate.
    )

    def __repr__(self) -> str:
        return (
            f"<WarehouseScan {self.id} {self.scan_type} "
            f"qty={self.qty} by_role={self.scanned_by_role}>"
        )


# ═════════════════════════════════════════════════════════════════════════════
# WarehouseAllocation — events reserving stock from warehouse
# ═════════════════════════════════════════════════════════════════════════════

class WarehouseAllocation(TenantScopedModel):
    """One product's reserved quantity for a specific event.

    Created/updated when Omar configures event stock. Decremented (via
    dispatched_qty going up) as physical DISPATCH scans move bottles to bars.

    DB-level CHECK constraints enforce:
      - both quantities non-negative
      - dispatched_qty <= reserved_qty (can't over-dispatch)

    Unique (tenant_id, event_id, product_id) means one allocation per
    product per event.
    """

    __tablename__ = "warehouse_allocations"

    event_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    reserved_qty = Column(Numeric(12, 2), nullable=False, default=0)
    dispatched_qty = Column(Numeric(12, 2), nullable=False, default=0)

    # Relationships
    event = relationship("Event", foreign_keys=[event_id])
    product = relationship("Product", foreign_keys=[product_id])

    __table_args__ = (
        CheckConstraint(
            "reserved_qty >= 0 AND dispatched_qty >= 0",
            name="ck_warehouse_allocations_nonneg",
        ),
        CheckConstraint(
            "dispatched_qty <= reserved_qty",
            name="ck_warehouse_allocations_dispatched_le_reserved",
        ),
        Index("ix_warehouse_allocations_tenant_id", "tenant_id"),
        Index(
            "ix_warehouse_allocations_tenant_event_product",
            "tenant_id",
            "event_id",
            "product_id",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<WarehouseAllocation event={self.event_id} "
            f"product={self.product_id} reserved={self.reserved_qty} "
            f"dispatched={self.dispatched_qty}>"
        )
