"""add event_products table (menu per event)

Revision ID: c1_add_event_products
Revises: b1_add_products_table
Create Date: 2026-04-16

Creates the event_products join table — the menu structure for each event.
Each row represents: "Product X is on the menu at Bar Y for Event Z,
at price P cents, with optional tier_rank override."

Design decisions (locked in Step 3 Q1-Q3 of the roadmap):
- bar_id is REQUIRED (menu items always tied to a specific bar for
  Dashboard per-bar aggregation and Slesh transaction matching)
- Hard uniqueness on (event_id, bar_id, product_id) — no duplicate
  entries of the same product at the same bar within one event
- price_cents is REQUIRED — Omar sets every price explicitly per event
- tier_rank NULL means "use the Product's default tier_rank"
- product_id has ON DELETE RESTRICT (protect catalog references)
- event_id / bar_id have ON DELETE CASCADE (deleting a draft event
  wipes its menu; bar deletion was already CASCADE in bars migration)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c1_add_event_products"
down_revision: str | None = "b1_add_products_table"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "event_products",
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
        # Event-specific overrides
        sa.Column(
            "price_cents",
            sa.Integer,
            nullable=False,
        ),
        sa.Column(
            "tier_rank_override",
            sa.SmallInteger,
            nullable=True,
            comment="When NULL, effective tier is inherited from Product.tier_rank",
        ),
        sa.Column(
            "is_available",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
            comment="Owner can temporarily disable menu items without deleting",
        ),
        sa.CheckConstraint(
            "price_cents >= 0",
            name="event_products_price_nonneg",
        ),
        sa.CheckConstraint(
            "tier_rank_override IS NULL OR (tier_rank_override >= 1 AND tier_rank_override <= 4)",
            name="event_products_tier_rank_range",
        ),
    )

    # Indexes
    op.create_index(
        "ix_event_products_event_id",
        "event_products",
        ["event_id"],
    )
    op.create_index(
        "ix_event_products_bar_id",
        "event_products",
        ["bar_id"],
    )
    op.create_index(
        "ix_event_products_product_id",
        "event_products",
        ["product_id"],
    )
    op.create_index(
        "ix_event_products_is_available",
        "event_products",
        ["is_available"],
    )

    # Unique: no duplicate product for (event, bar) pair
    op.create_index(
        "uq_event_products_event_bar_product",
        "event_products",
        ["event_id", "bar_id", "product_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_event_products_event_bar_product", table_name="event_products")
    op.drop_index("ix_event_products_is_available", table_name="event_products")
    op.drop_index("ix_event_products_product_id", table_name="event_products")
    op.drop_index("ix_event_products_bar_id", table_name="event_products")
    op.drop_index("ix_event_products_event_id", table_name="event_products")
    op.drop_table("event_products")
