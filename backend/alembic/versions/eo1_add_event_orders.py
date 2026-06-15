"""eo1 add event_orders table

Per-Slesh-order financial extras (VAT, deposits, fiscal totals,
discounts, order type) plus per-order line-count metadata.

Populated by order_ingester alongside stock_transactions, one row
per Slesh order. Enables the revenue-breakdown popup and any
future cross-event order-level analytics.

Revision ID: eo1_add_event_orders
Revises: x1_add_pos_line_status
Create Date: 2026-06-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "eo1_add_event_orders"
down_revision = "x1_add_pos_line_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_orders",

        # Primary key
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),

        # Multi-tenant + event scope
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id",  postgresql.UUID(as_uuid=True), nullable=False),

        # Slesh identifiers
        sa.Column("slesh_order_id", sa.Text, nullable=False),
        sa.Column("slesh_shop_id",  sa.Text, nullable=True),
        sa.Column("bar_id", postgresql.UUID(as_uuid=True), nullable=True),

        # cash-desk | express | experience  (Slesh _type)
        sa.Column("order_type", sa.Text, nullable=False),

        # Financial fields — cents only, no float drift
        sa.Column("subtotal_cents",      sa.BigInteger, nullable=True),
        sa.Column("vat_cents",           sa.BigInteger, nullable=True),
        sa.Column("deposit_cents",       sa.BigInteger, nullable=True),
        sa.Column("fiscal_gross_cents",  sa.BigInteger, nullable=True),
        sa.Column("fiscal_net_cents",    sa.BigInteger, nullable=True),
        sa.Column("discount_cents",      sa.BigInteger, nullable=True),
        sa.Column("pre_promo_cents",     sa.BigInteger, nullable=True),

        # Metadata
        sa.Column("payment_type",         sa.Text, nullable=True),
        sa.Column("cart_line_count",      sa.Integer, nullable=False, server_default="0"),
        sa.Column("confirmed_line_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("refunded_line_count",  sa.Integer, nullable=False, server_default="0"),

        # Safety net — full Slesh extras dict for any field we do not
        # explicitly model. Future migrations may promote fields out
        # of here into typed columns.
        sa.Column("raw_extras", postgresql.JSONB, nullable=True),

        # Timestamps
        sa.Column("created_at_slesh", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at",      sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),

        sa.PrimaryKeyConstraint("id", name="pk_event_orders"),
        sa.UniqueConstraint("tenant_id", "slesh_order_id",
                            name="uq_event_orders_tenant_slesh_order"),
    )

    op.create_index(
        "ix_event_orders_tenant_event_time",
        "event_orders",
        ["tenant_id", "event_id", "created_at_slesh"],
    )
    op.create_index(
        "ix_event_orders_event_type",
        "event_orders",
        ["event_id", "order_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_orders_event_type", table_name="event_orders")
    op.drop_index("ix_event_orders_tenant_event_time", table_name="event_orders")
    op.drop_table("event_orders")
