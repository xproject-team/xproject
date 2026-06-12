"""event_storage tables: supplier_products + event_stock_items

Revision ID: y1_event_storage_tables
Revises: x2_auto_created_bars
Create Date: 2026-06-12

Two new tables for Phase 2:

supplier_products
    Master list of items available from suppliers (Partesa for Sundance 1).
    Reusable across events. Identity is (tenant_id, supplier_sku).
    Seeded once from the Partesa invoice in commit 4; grows organically
    via wizard "+ Add new" thereafter.

event_stock_items
    Per-event purchase rows. One row per (event, supplier_product)
    declaring how many of that item were bought for this event.
    Unique on (tenant_id, event_id, supplier_product_id) so the wizard's
    bulk-upsert is idempotent. Drives warehouse + inventory KPIs.

FK policy:
    tenant_id      -> CASCADE   (tenant deletion wipes its data)
    event_id       -> CASCADE   (event deletion wipes its declarations)
    supplier_prod  -> RESTRICT  (deleting a master-list item is blocked
                                 if any event still references it; forces
                                 explicit cleanup, prevents accidental
                                 loss of historical purchase data)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "y1_event_storage_tables"
down_revision = "x2_auto_created_bars"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supplier_products",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "supplier_name", sa.String(128),
            nullable=False, server_default="Partesa",
        ),
        sa.Column("supplier_sku", sa.String(64), nullable=False),
        sa.Column("item_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("default_unit", sa.String(16), nullable=False),
        sa.Column(
            "units_per_pack", sa.Integer,
            nullable=False, server_default="1",
        ),
        sa.Column("volume_per_unit_ml", sa.Integer, nullable=True),
        sa.Column("last_unit_price_eur", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "supplier_sku",
            name="uq_supplier_products_tenant_sku",
        ),
    )
    op.create_index(
        "ix_supplier_products_tenant_id",
        "supplier_products", ["tenant_id"],
    )
    op.create_index(
        "ix_supplier_products_category",
        "supplier_products", ["category"],
    )

    op.create_table(
        "event_stock_items",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "supplier_product_id", postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("qty_received", sa.Numeric(10, 2), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("unit_price_eur", sa.Numeric(10, 2), nullable=True),
        sa.Column("discount_amount_eur", sa.Numeric(10, 2), nullable=True),
        sa.Column("line_total_eur", sa.Numeric(12, 2), nullable=True),
        sa.Column("vat_pct", sa.Integer, nullable=True, server_default="22"),
        sa.Column("invoice_number", sa.String(64), nullable=True),
        sa.Column("invoice_date", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_product_id"], ["supplier_products.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "event_id", "supplier_product_id",
            name="uq_event_stock_items_tenant_event_sp",
        ),
    )
    op.create_index(
        "ix_event_stock_items_event_id",
        "event_stock_items", ["event_id"],
    )
    op.create_index(
        "ix_event_stock_items_supplier_product_id",
        "event_stock_items", ["supplier_product_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_stock_items_supplier_product_id",
        table_name="event_stock_items",
    )
    op.drop_index(
        "ix_event_stock_items_event_id", table_name="event_stock_items",
    )
    op.drop_table("event_stock_items")
    op.drop_index(
        "ix_supplier_products_category", table_name="supplier_products",
    )
    op.drop_index(
        "ix_supplier_products_tenant_id", table_name="supplier_products",
    )
    op.drop_table("supplier_products")
