"""event_category_ingredients — Slesh-category → ingredient-pool depletion rules

Revision ID: y3_event_category_ingredients
Revises: y2_event_stock_bar_allocations
Create Date: 2026-06-13

Sundance 14 ml-depletion logic. Each row says:
  "When a sale of <slesh_category> rings up at <bar_id or any bar>,
   subtract <ml_per_sale> from <supplier_product_id> at the firing bar."

Worst-case math: multiple rows can share the same (event, slesh_category)
to deplete several supplier_products in parallel (every Signature sale
hits Vodka, Gin, Rum, Tequila simultaneously). This is intentional —
high-recall alerts, false positives << false negatives in event ops.

bar_id NULL = rule applies to every bar selling this category (default).
bar_id set  = rule restricted to that specific bar (e.g. GIN No 3
              sponsor — Premium category at NO.3 BAR depletes one
              extra bottle that other bars don't have).

threshold_pct_warn / threshold_pct_empty drive auto-alert firing on
status flips (healthy → low → critical).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "y3_event_category_ingredients"
down_revision = "y2_event_stock_bar_allocations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_category_ingredients",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column(
            "event_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column("slesh_category", sa.String(128), nullable=False),
        sa.Column(
            "supplier_product_id", postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "ml_per_sale", sa.Numeric(10, 2), nullable=False,
        ),
        sa.Column(
            "bar_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column(
            "threshold_pct_warn", sa.Numeric(5, 2),
            nullable=False, server_default="70.00",
        ),
        sa.Column(
            "threshold_pct_empty", sa.Numeric(5, 2),
            nullable=False, server_default="100.00",
        ),
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
    )
    # Lookup index for the depletion service hot path.
    op.create_index(
        "ix_event_cat_ing_event_cat",
        "event_category_ingredients",
        ["event_id", "slesh_category"],
    )
    op.create_index(
        "ix_event_cat_ing_event_sp",
        "event_category_ingredients",
        ["event_id", "supplier_product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_cat_ing_event_sp", table_name="event_category_ingredients")
    op.drop_index("ix_event_cat_ing_event_cat", table_name="event_category_ingredients")
    op.drop_table("event_category_ingredients")
