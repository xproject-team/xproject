"""customer_sessions + customer_purchases — Phase 2 feature layer

Revision ID: ac1
Revises: ab1
Create Date: 2026-07-29

Two new tables, built exclusively from Slesh-sourced data (event_orders,
stock_transactions, products, bars). Populated by
app/scripts/build_customer_features.py, never written to directly by
the application.

customer_sessions
    One row per (event_id, customer_key) — the per-customer aggregate
    profile a model trains on. customer_key is
    event_orders.raw_extras->'user'->>'_id'; orders without one are
    never represented here.

customer_purchases
    One row per drink/food line attributed to a customer, joined via
    stock_transactions.source_idempotency_key back to
    event_orders.slesh_order_id. ordered_at is always
    event_orders.created_at_slesh (the poller's ingestion timestamp on
    stock_transactions is never used for this table).

FK policy:
    tenant_id, event_id -> CASCADE (tenant/event deletion wipes derived data)
    product_id          -> RESTRICT (blocks deleting a product still
                                      referenced by purchase history)
    bar_id, first_bar_id -> SET NULL (a bar can be removed without
                                       destroying purchase/session rows)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ac1"
down_revision = "ab1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                   server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_key", sa.String(64), nullable=False),

        sa.Column("first_order_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_order_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "session_minutes", sa.Numeric(10, 2), nullable=False,
            comment="last_order_at - first_order_at, in minutes. This is "
                    "time BETWEEN first and last purchase, NOT true "
                    "attendance duration — do not read it as time-on-site.",
        ),

        sa.Column("order_count", sa.Integer, nullable=False),
        sa.Column("total_spend_cents", sa.BigInteger, nullable=False),
        sa.Column("avg_order_cents", sa.BigInteger, nullable=False),

        sa.Column("distinct_bars", sa.Integer, nullable=False),
        sa.Column("first_bar_id", postgresql.UUID(as_uuid=True), nullable=True),

        sa.Column(
            "is_registered", sa.Boolean, nullable=True,
            comment="email domain != 'slesh.it'. NULL when none of this "
                    "customer's orders carry a customer_email at all.",
        ),
        sa.Column("email_domain", sa.Text, nullable=True,
                   comment="Domain only. The full email address is never stored here."),
        sa.Column("user_source", sa.String(16), nullable=False, server_default="live",
                   comment="'live' (captured by the poller) or 'backfill' "
                           "(recovered after the fact — Sundance 14 provenance)."),

        sa.Column("drink_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("food_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("beer_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cocktail_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("spritz_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("wine_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("premium_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("other_count", sa.Integer, nullable=False, server_default="0"),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),

        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["first_bar_id"], ["bars.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("event_id", "customer_key", name="uq_customer_sessions_event_customer"),
    )
    op.create_index("ix_customer_sessions_tenant_id", "customer_sessions", ["tenant_id"])

    op.create_table(
        "customer_purchases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                   server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_key", sa.String(64), nullable=False),

        sa.Column("slesh_order_id", sa.String(64), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_name", sa.Text, nullable=False),
        sa.Column(
            "category", sa.String(16), nullable=False,
            comment="One of beer|cocktail|spritz|wine|premium|other (drink "
                    "bucket) or food (all product_type=FOOD lines).",
        ),

        sa.Column("bar_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("qty", sa.Numeric(12, 3), nullable=False),
        sa.Column("price_cents", sa.Integer, nullable=True),

        sa.Column(
            "ordered_at", sa.DateTime(timezone=True), nullable=False,
            comment="Always event_orders.created_at_slesh. NEVER "
                    "stock_transactions.created_at (ingestion time).",
        ),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),

        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bar_id"], ["bars.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_customer_purchases_event_customer", "customer_purchases", ["event_id", "customer_key"])
    op.create_index("ix_customer_purchases_event_ordered_at", "customer_purchases", ["event_id", "ordered_at"])
    op.create_index("ix_customer_purchases_event_category", "customer_purchases", ["event_id", "category"])


def downgrade() -> None:
    op.drop_index("ix_customer_purchases_event_category", table_name="customer_purchases")
    op.drop_index("ix_customer_purchases_event_ordered_at", table_name="customer_purchases")
    op.drop_index("ix_customer_purchases_event_customer", table_name="customer_purchases")
    op.drop_table("customer_purchases")

    op.drop_index("ix_customer_sessions_tenant_id", table_name="customer_sessions")
    op.drop_table("customer_sessions")
