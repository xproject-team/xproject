"""event_stock_bar_allocations — per-event per-bar dispatch log

Revision ID: y2_event_stock_bar_allocations
Revises: y1_event_storage_tables
Create Date: 2026-06-12

History-preserving table: every dispatch (Omar sends N of a
supplier_product to a bar) creates a NEW row. No unique constraint.
Aggregations SUM across rows.

FK policy:
    tenant_id            -> CASCADE   tenant deletion wipes data
    event_id             -> CASCADE   event deletion wipes allocations
    supplier_product_id  -> RESTRICT  catalog deletion blocked while
                                      referenced (preserve history)
    bar_id               -> CASCADE   bar deletion (rare; e.g. via
                                      merge endpoint with no stock)
                                      wipes its allocations
    dispatched_by_user_id -> SET NULL user deletion preserves history
                                      with attribution lost
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "y2_event_stock_bar_allocations"
down_revision = "y1_event_storage_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_stock_bar_allocations",
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
        sa.Column("bar_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("qty_allocated", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "dispatched_by_user_id", postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
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
        sa.ForeignKeyConstraint(
            ["bar_id"], ["bars.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dispatched_by_user_id"], ["users.id"], ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_event_stock_bar_allocations_event_id",
        "event_stock_bar_allocations", ["event_id"],
    )
    op.create_index(
        "ix_event_stock_bar_allocations_supplier_product_id",
        "event_stock_bar_allocations", ["supplier_product_id"],
    )
    op.create_index(
        "ix_event_stock_bar_allocations_bar_id",
        "event_stock_bar_allocations", ["bar_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_stock_bar_allocations_bar_id",
        table_name="event_stock_bar_allocations",
    )
    op.drop_index(
        "ix_event_stock_bar_allocations_supplier_product_id",
        table_name="event_stock_bar_allocations",
    )
    op.drop_index(
        "ix_event_stock_bar_allocations_event_id",
        table_name="event_stock_bar_allocations",
    )
    op.drop_table("event_stock_bar_allocations")
