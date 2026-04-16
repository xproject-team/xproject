"""add products table with enums

Revision ID: b1_add_products_table
Revises: a9_event_version
Create Date: 2026-04-16

Creates:
- Three Postgres ENUM types:
    product_type      (drink, food, ingredient, supply)
    product_category  (Omar's confirmed drink taxonomy, 8 values)
    product_unit      (bottle, glass, can, draft_glass, shot, piece, gram, ml)
- products table (tenant-scoped catalog, soft-delete via is_archived)
- Partial unique index preventing duplicate active products per tenant
  (unique on tenant_id + name + product_type WHERE is_archived = false)

Follows the pattern established in a9_event_version:
- Native Postgres enums for type safety
- TIMESTAMPTZ for timezone-aware timestamps
- UUID primary keys
- Indexes on commonly-filtered columns (tenant_id, product_type, is_archived)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b1_add_products_table"
down_revision: str | None = "a9_event_version"
branch_labels: str | None = None
depends_on: str | None = None


# ─── Enum definitions (created in upgrade, dropped in downgrade) ──────────────

PRODUCT_TYPE_VALUES = ("drink", "food", "ingredient", "supply")

PRODUCT_CATEGORY_VALUES = (
    # Beers
    "beer_draft",
    "beer_bottle",
    # Cocktails
    "basic_cocktail",
    "premium_cocktail",
    # Wines
    "wine_red",
    "wine_white",
    "wine_sparkling",
    # Non-alcoholic
    "soft_drink",
)

PRODUCT_UNIT_VALUES = (
    "bottle",
    "glass",
    "can",
    "draft_glass",
    "shot",
    "piece",
    "gram",
    "ml",
)


def upgrade() -> None:
    # ─── Create enums first ───────────────────────────────────────────────────
    product_type_enum = postgresql.ENUM(
        *PRODUCT_TYPE_VALUES,
        name="product_type",
        create_type=False,  # we create it manually below to control the order
    )
    product_category_enum = postgresql.ENUM(
        *PRODUCT_CATEGORY_VALUES,
        name="product_category",
        create_type=False,
    )
    product_unit_enum = postgresql.ENUM(
        *PRODUCT_UNIT_VALUES,
        name="product_unit",
        create_type=False,
    )

    product_type_enum.create(op.get_bind(), checkfirst=True)
    product_category_enum.create(op.get_bind(), checkfirst=True)
    product_unit_enum.create(op.get_bind(), checkfirst=True)

    # ─── Create products table ────────────────────────────────────────────────
    op.create_table(
        "products",
        # Inherited TenantScopedModel columns
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
        # Product-specific columns
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "product_type",
            product_type_enum,
            nullable=False,
        ),
        sa.Column(
            "category",
            product_category_enum,
            nullable=True,  # only drinks have category
        ),
        sa.Column(
            "tier_rank",
            sa.SmallInteger,
            nullable=True,  # only drinks have tier_rank
        ),
        sa.Column(
            "unit",
            product_unit_enum,
            nullable=False,
        ),
        sa.Column(
            "default_price_cents",
            sa.Integer,
            nullable=True,
        ),
        sa.Column(
            "is_archived",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        # Constraints
        sa.CheckConstraint(
            "tier_rank IS NULL OR (tier_rank >= 1 AND tier_rank <= 4)",
            name="products_tier_rank_range",
        ),
        sa.CheckConstraint(
            "default_price_cents IS NULL OR default_price_cents >= 0",
            name="products_price_nonneg",
        ),
    )

    # ─── Indexes ──────────────────────────────────────────────────────────────
    op.create_index(
        "ix_products_product_type",
        "products",
        ["product_type"],
    )
    op.create_index(
        "ix_products_category",
        "products",
        ["category"],
    )
    op.create_index(
        "ix_products_is_archived",
        "products",
        ["is_archived"],
    )

    # ─── Partial unique index: no duplicate active products per tenant ───────
    op.create_index(
        "uq_products_tenant_name_type_active",
        "products",
        ["tenant_id", "name", "product_type"],
        unique=True,
        postgresql_where=sa.text("is_archived = false"),
    )


def downgrade() -> None:
    op.drop_index("uq_products_tenant_name_type_active", table_name="products")
    op.drop_index("ix_products_is_archived", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_index("ix_products_product_type", table_name="products")
    op.drop_table("products")

    # Drop enums AFTER the table that used them
    postgresql.ENUM(name="product_unit").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="product_category").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="product_type").drop(op.get_bind(), checkfirst=True)
