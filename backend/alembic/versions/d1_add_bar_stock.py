"""add bar_stock table (per-bar inventory ledger)

Revision ID: d1_add_bar_stock
Revises: c1_add_event_products
Create Date: 2026-04-16

Creates the bar_stock table — the per-event, per-bar, per-product
inventory state. Each row answers: "how much of this product is
currently at this bar for this event?"

Three quantity columns track the full lifecycle:
- allocated_qty: transferred in at event start
- current_qty:   what's physically there right now (decremented on consume)
- returned_qty:  transferred out at event end

Reconciliation logic (Step 6 will use this):
    expected_consumption = allocated_qty - current_qty - returned_qty
    actual_consumption   = SUM(stock_transactions WHERE action=consume)
    anomaly = abs(expected - actual)

Design decisions (locked Step 4 Q1-Q3):
- Unit is inherited from Product (not stored here) — Product.unit is
  the single source of truth. Downstream code joins when it needs
  a unit display.
- bar_id has ON DELETE CASCADE (deleting a bar wipes its stock rows)
- product_id has ON DELETE RESTRICT (catalog protected)
- Unique on (event_id, bar_id, product_id) — one stock row per triple
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d1_add_bar_stock"
down_revision: str | None = "c1_add_event_products"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "bar_stock",
        # TenantScopedModel columns
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
        # Relationships
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Quantity columns
        sa.Column(
            "allocated_qty",
            sa.Integer,
            nullable=False,
            comment="Transferred IN at event start. Baseline for reconciliation.",
        ),
        sa.Column(
            "current_qty",
            sa.Integer,
            nullable=False,
            comment="What's physically at the bar right now.",
        ),
        sa.Column(
            "returned_qty",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
            comment="Transferred OUT at event end (unused stock back to warehouse).",
        ),
        # Invariants
        sa.CheckConstraint(
            "allocated_qty >= 0",
            name="bar_stock_allocated_nonneg",
        ),
        sa.CheckConstraint(
            "current_qty >= 0",
            name="bar_stock_current_nonneg",
        ),
        sa.CheckConstraint(
            "returned_qty >= 0",
            name="bar_stock_returned_nonneg",
        ),
        sa.CheckConstraint(
            "current_qty <= allocated_qty",
            name="bar_stock_current_lte_allocated",
        ),
        sa.CheckConstraint(
            "returned_qty <= allocated_qty",
            name="bar_stock_returned_lte_allocated",
        ),
    )

    # Secondary indexes for common queries
    op.create_index(
        "ix_bar_stock_event_id",
        "bar_stock",
        ["event_id"],
    )
    op.create_index(
        "ix_bar_stock_bar_id",
        "bar_stock",
        ["bar_id"],
    )
    op.create_index(
        "ix_bar_stock_product_id",
        "bar_stock",
        ["product_id"],
    )

    # Unique: one stock row per (event, bar, product)
    op.create_index(
        "uq_bar_stock_event_bar_product",
        "bar_stock",
        ["event_id", "bar_id", "product_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_bar_stock_event_bar_product", table_name="bar_stock")
    op.drop_index("ix_bar_stock_product_id", table_name="bar_stock")
    op.drop_index("ix_bar_stock_bar_id", table_name="bar_stock")
    op.drop_index("ix_bar_stock_event_id", table_name="bar_stock")
    op.drop_table("bar_stock")
