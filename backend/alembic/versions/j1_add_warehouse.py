"""add warehouse module (invoices, inventory, scans, allocations)

Revision ID: j1_add_warehouse
Revises: i1_add_predictions
Create Date: 2026-04-24 09:00:00.000000

Warehouse module storage. See docs/warehouse-module-spec.md §4.

Creates 4 enums + 5 tables:
  - enum `invoicestatus`   : EXPECTED, SCANNING, PAUSED, VERIFIED,
                             DISCREPANCY, DISPUTED, CLOSED
  - enum `scantype`        : INTAKE, DISPATCH, RETURN, ADJUSTMENT,
                             INSPECT, CONSUMED
  - enum `scannerrole`     : owner, manager, bartender, warehouse_keeper
                             (snapshot of user role at scan time)
  - enum `invoicelinekind` : catalog_product, miscellaneous

Tables:
  delivery_invoices       — hero entity, one per supplier delivery
  invoice_items           — line items (expected products + quantities + prices)
  warehouse_inventory     — tenant-scoped product stock (NOT event-scoped)
  warehouse_scans         — append-only audit trail with role snapshots
  warehouse_allocations   — events reserve stock from warehouse

Design decisions encoded here (from spec §4):
  - supplier_name is varchar(255) freetext — §4.X supplier modeling
    deferred pending real invoice sample from Omar
  - warehouse_inventory is tenant-scoped (one row per product per tenant),
    NOT event-scoped. Events allocate from here via warehouse_allocations.
  - warehouse_scans.scanned_by_role is a snapshot enum — never updated
    even if user's role later changes. Preserves historical truth.
  - invoice_items can reference either a catalog product OR be a freetext
    "miscellaneous" row (Q6 flexible structure).
  - warehouse_scans.invoice_id is NULL for non-intake scans; SET for INTAKE
    scans during an active invoice session.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "j1_add_warehouse"
down_revision = "i1_add_predictions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════════════
    # Enums
    # ═══════════════════════════════════════════════════════════════════════

    invoice_status = postgresql.ENUM(
        "EXPECTED", "SCANNING", "PAUSED", "VERIFIED",
        "DISCREPANCY", "DISPUTED", "CLOSED",
        name="invoicestatus",
        create_type=False,
    )
    scan_type_enum = postgresql.ENUM(
        "INTAKE", "DISPATCH", "RETURN", "ADJUSTMENT",
        "INSPECT", "CONSUMED",
        name="scantype",
        create_type=False,
    )
    scanner_role = postgresql.ENUM(
        "owner", "manager", "bartender", "warehouse_keeper",
        name="scannerrole",
        create_type=False,
    )
    invoice_line_kind = postgresql.ENUM(
        "catalog_product", "miscellaneous",
        name="invoicelinekind",
        create_type=False,
    )

    invoice_status.create(op.get_bind(), checkfirst=True)
    scan_type_enum.create(op.get_bind(), checkfirst=True)
    scanner_role.create(op.get_bind(), checkfirst=True)
    invoice_line_kind.create(op.get_bind(), checkfirst=True)

    # ═══════════════════════════════════════════════════════════════════════
    # 1. delivery_invoices — the hero entity
    # ═══════════════════════════════════════════════════════════════════════

    op.create_table(
        "delivery_invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("invoice_number", sa.String(128), nullable=True),
        # NOTE: supplier_name is freetext for v1.0 per spec §4.X.
        # Leaves room for future supplier FK migration without breaking.
        sa.Column("supplier_name", sa.String(255), nullable=False),
        sa.Column("expected_arrival_date", sa.Date(), nullable=False),
        sa.Column("status", invoice_status, nullable=False,
                  server_default="EXPECTED"),
        sa.Column("scan_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scan_closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_delivery_invoices_tenant_id",
        "delivery_invoices", ["tenant_id"],
    )
    op.create_index(
        "ix_delivery_invoices_tenant_status",
        "delivery_invoices", ["tenant_id", "status"],
    )
    op.create_index(
        "ix_delivery_invoices_tenant_arrival_date",
        "delivery_invoices",
        ["tenant_id", sa.text("expected_arrival_date DESC")],
    )
    op.create_index(
        "ix_delivery_invoices_tenant_supplier",
        "delivery_invoices", ["tenant_id", "supplier_name"],
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 2. invoice_items — line items per invoice
    # ═══════════════════════════════════════════════════════════════════════

    op.create_table(
        "invoice_items",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("delivery_invoices.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", invoice_line_kind, nullable=False,
                  server_default="catalog_product"),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("products.id", ondelete="RESTRICT"),
                  nullable=True),
        sa.Column("miscellaneous_description", sa.String(255), nullable=True),
        sa.Column("expected_qty", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=True),
        sa.Column("line_total_cents", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        # Enforce: every line must describe SOMETHING
        sa.CheckConstraint(
            "(kind = 'catalog_product' AND product_id IS NOT NULL) OR "
            "(kind = 'miscellaneous' AND miscellaneous_description IS NOT NULL)",
            name="ck_invoice_items_has_description",
        ),
        # Enforce: catalog lines don't have freetext, misc lines don't have FK
        sa.CheckConstraint(
            "(kind = 'catalog_product' AND miscellaneous_description IS NULL) OR "
            "(kind = 'miscellaneous' AND product_id IS NULL)",
            name="ck_invoice_items_kind_consistency",
        ),
    )
    op.create_index(
        "ix_invoice_items_tenant_id",
        "invoice_items", ["tenant_id"],
    )
    op.create_index(
        "ix_invoice_items_invoice_id",
        "invoice_items", ["invoice_id"],
    )
    op.create_index(
        "ix_invoice_items_tenant_product",
        "invoice_items", ["tenant_id", "product_id"],
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 3. warehouse_inventory — tenant-scoped product stock
    # ═══════════════════════════════════════════════════════════════════════

    op.create_table(
        "warehouse_inventory",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("products.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("current_qty", sa.Numeric(12, 2), nullable=False,
                  server_default="0"),
        sa.Column("low_stock_threshold", sa.Numeric(12, 2), nullable=True),
        sa.Column("last_movement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        # Stock can't go below 0 — enforced at DB level
        sa.CheckConstraint(
            "current_qty >= 0",
            name="ck_warehouse_inventory_nonneg",
        ),
    )
    op.create_index(
        "ix_warehouse_inventory_tenant_id",
        "warehouse_inventory", ["tenant_id"],
    )
    op.create_index(
        "ix_warehouse_inventory_tenant_product",
        "warehouse_inventory", ["tenant_id", "product_id"],
        unique=True,  # One inventory row per product per tenant
    )
    op.create_index(
        "ix_warehouse_inventory_tenant_low",
        "warehouse_inventory",
        ["tenant_id", "current_qty"],
        # "At Risk" KPI query — finds low-stock products fast
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 4. warehouse_scans — append-only audit trail
    # ═══════════════════════════════════════════════════════════════════════

    op.create_table(
        "warehouse_scans",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("scan_type", scan_type_enum, nullable=False),
        # INTAKE scans set invoice_id; others leave it NULL
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("delivery_invoices.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("products.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("barcode_raw", sa.String(255), nullable=True),
        sa.Column("qty", sa.Numeric(12, 2), nullable=False,
                  server_default="1"),
        # DISPATCH/RETURN/CONSUMED set these; INTAKE leaves NULL
        sa.Column("event_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("events.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("bar_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("bars.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("is_unexpected", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("pending_review", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("scanned_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        # Snapshot of role AT SCAN TIME — never updated after insert
        sa.Column("scanned_by_role", scanner_role, nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        # Standard TenantScopedModel timestamps — required because the ORM
        # inherits from TenantScopedModel. scanned_at is semantically distinct
        # (the physical scan moment); these track DB row lifecycle.
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        # Scan qty must be positive
        sa.CheckConstraint(
            "qty > 0",
            name="ck_warehouse_scans_qty_positive",
        ),
    )
    op.create_index(
        "ix_warehouse_scans_tenant_id",
        "warehouse_scans", ["tenant_id"],
    )
    op.create_index(
        "ix_warehouse_scans_tenant_at",
        "warehouse_scans",
        ["tenant_id", sa.text("scanned_at DESC")],
        # Powers the activity feed (latest 20)
    )
    op.create_index(
        "ix_warehouse_scans_tenant_invoice",
        "warehouse_scans", ["tenant_id", "invoice_id"],
        # All scans for one invoice session
    )
    op.create_index(
        "ix_warehouse_scans_tenant_event_bar",
        "warehouse_scans", ["tenant_id", "event_id", "bar_id"],
        # DISPATCH history per bar per event
    )
    # Partial index: fast lookup of scans needing Owner approval
    op.create_index(
        "ix_warehouse_scans_pending_review",
        "warehouse_scans", ["tenant_id", "scanned_at"],
        postgresql_where=sa.text("pending_review = true"),
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 5. warehouse_allocations — events reserving stock
    # ═══════════════════════════════════════════════════════════════════════

    op.create_table(
        "warehouse_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("events.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("products.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("reserved_qty", sa.Numeric(12, 2), nullable=False,
                  server_default="0"),
        sa.Column("dispatched_qty", sa.Numeric(12, 2), nullable=False,
                  server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        # Both quantities must be non-negative
        sa.CheckConstraint(
            "reserved_qty >= 0 AND dispatched_qty >= 0",
            name="ck_warehouse_allocations_nonneg",
        ),
        # Can't dispatch more than was reserved
        sa.CheckConstraint(
            "dispatched_qty <= reserved_qty",
            name="ck_warehouse_allocations_dispatched_le_reserved",
        ),
    )
    op.create_index(
        "ix_warehouse_allocations_tenant_id",
        "warehouse_allocations", ["tenant_id"],
    )
    op.create_index(
        "ix_warehouse_allocations_tenant_event_product",
        "warehouse_allocations",
        ["tenant_id", "event_id", "product_id"],
        unique=True,  # One allocation per event per product
    )


def downgrade() -> None:
    # Drop in reverse order of creation to respect FKs
    op.drop_index(
        "ix_warehouse_allocations_tenant_event_product",
        table_name="warehouse_allocations",
    )
    op.drop_index(
        "ix_warehouse_allocations_tenant_id",
        table_name="warehouse_allocations",
    )
    op.drop_table("warehouse_allocations")

    op.drop_index("ix_warehouse_scans_pending_review", table_name="warehouse_scans")
    op.drop_index("ix_warehouse_scans_tenant_event_bar", table_name="warehouse_scans")
    op.drop_index("ix_warehouse_scans_tenant_invoice", table_name="warehouse_scans")
    op.drop_index("ix_warehouse_scans_tenant_at", table_name="warehouse_scans")
    op.drop_index("ix_warehouse_scans_tenant_id", table_name="warehouse_scans")
    op.drop_table("warehouse_scans")

    op.drop_index(
        "ix_warehouse_inventory_tenant_low",
        table_name="warehouse_inventory",
    )
    op.drop_index(
        "ix_warehouse_inventory_tenant_product",
        table_name="warehouse_inventory",
    )
    op.drop_index(
        "ix_warehouse_inventory_tenant_id",
        table_name="warehouse_inventory",
    )
    op.drop_table("warehouse_inventory")

    op.drop_index("ix_invoice_items_tenant_product", table_name="invoice_items")
    op.drop_index("ix_invoice_items_invoice_id", table_name="invoice_items")
    op.drop_index("ix_invoice_items_tenant_id", table_name="invoice_items")
    op.drop_table("invoice_items")

    op.drop_index(
        "ix_delivery_invoices_tenant_supplier",
        table_name="delivery_invoices",
    )
    op.drop_index(
        "ix_delivery_invoices_tenant_arrival_date",
        table_name="delivery_invoices",
    )
    op.drop_index(
        "ix_delivery_invoices_tenant_status",
        table_name="delivery_invoices",
    )
    op.drop_index(
        "ix_delivery_invoices_tenant_id",
        table_name="delivery_invoices",
    )
    op.drop_table("delivery_invoices")

    # Drop enums LAST (after all tables using them are gone)
    postgresql.ENUM(name="invoicelinekind").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="scannerrole").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="scantype").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="invoicestatus").drop(op.get_bind(), checkfirst=True)
