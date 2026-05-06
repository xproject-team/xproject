"""add recipe_templates and recipe_template_items

Revision ID: o3_add_recipe_templates
Revises: o2_add_venue_geo
Create Date: 2026-05-04

Two new tables for the system-wide standard cocktail catalog (IBA-curated,
~31 entries). Both are tenant-free — the catalog is universal. Per-tenant
recipe definitions still live in the existing `recipes` table.

Round-trip tested:
  alembic downgrade -1   ->   alembic upgrade head    (clean)

Spec: docs/slesh-integration-roadmap.md (Phase F).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID


revision: str = "o3_add_recipe_templates"
down_revision: Union[str, None] = "o2_add_venue_geo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ─── recipe_templates (parent) ───────────────────────────────────
    op.create_table(
        "recipe_templates",
        sa.Column(
            "id",
            PgUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "slug",
            sa.String(length=64),
            nullable=False,
            comment=(
                "Stable, code-friendly identifier (snake_case). "
                "Used for re-seeding without duplicating rows."
            ),
        ),
        sa.Column("name",        sa.String(length=128), nullable=False),
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
            comment="IBA category: contemporary | unforgettable | new_era | shooter | wine | beer",
        ),
        sa.Column("description", sa.Text(),             nullable=True),
        sa.Column(
            "glass_type",
            sa.String(length=32),
            nullable=True,
            comment="Bartender reference glass type (highball, rocks, martini, etc.)",
        ),
        sa.Column(
            "total_ml",
            sa.Numeric(10, 2),
            nullable=True,
            comment=(
                "Denormalized sum of ml-unit ingredient lines. "
                "NULL when units are mixed (e.g. piece, dash). "
                "Computed by the seed script for sortable picker."
            ),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("slug", name="uq_recipe_templates_slug"),
    )
    op.create_index(
        "ix_recipe_templates_category",
        "recipe_templates",
        ["category"],
    )

    # ─── recipe_template_items (children) ─────────────────────────────
    op.create_table(
        "recipe_template_items",
        sa.Column(
            "id",
            PgUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "template_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("recipe_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingredient_role",
            sa.String(length=64),
            nullable=False,
            comment=(
                "Logical role (e.g. 'vodka', 'lime_juice'). NOT a Product UUID. "
                "Per-tenant binding to actual Products happens in `recipes` / "
                "`recipe_items` when an Owner adopts this template."
            ),
        ),
        sa.Column(
            "ingredient_label",
            sa.String(length=128),
            nullable=False,
            comment="Display label for the role (e.g. 'White Rum').",
        ),
        sa.Column("qty",   sa.Numeric(10, 3),     nullable=False),
        sa.Column("unit",  sa.String(length=32),  nullable=False),
        sa.Column(
            "order_index",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Display order within the template (0-based).",
        ),
        sa.CheckConstraint(
            "qty > 0",
            name="recipe_template_items_qty_positive",
        ),
        sa.UniqueConstraint(
            "template_id", "ingredient_role",
            name="uq_recipe_template_items_role",
        ),
    )
    op.create_index(
        "ix_recipe_template_items_template",
        "recipe_template_items",
        ["template_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_recipe_template_items_template", table_name="recipe_template_items")
    op.drop_table("recipe_template_items")
    op.drop_index("ix_recipe_templates_category", table_name="recipe_templates")
    op.drop_table("recipe_templates")
