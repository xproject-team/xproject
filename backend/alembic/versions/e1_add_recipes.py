"""add recipes and recipe_items tables

Revision ID: e1_add_recipes
Revises: d1_add_bar_stock
Create Date: 2026-04-17

Creates the recipe structure for Products marked as drinks.

Two-table model (locked in Step 5 Q3):

    recipes                          — header per drink
    recipe_items                     — the ingredient lines

Design decisions:
- Recipes are TENANT-GLOBAL (Q1): one recipe per drink per tenant,
  not per-event. If an event needs a different recipe, create a
  different Product in the catalog.
- Any product_type EXCEPT the drink itself can be an ingredient (Q2).
  Beer-based cocktails (Kalimotxo, Michelada) valid; self-reference
  blocked by service-layer check (not DB, because DB CHECK cannot
  compare across tables).
- recipes.drink_product_id FK RESTRICT (don't orphan recipes when
  someone tries to delete a drink product).
- recipe_items.recipe_id FK CASCADE (deleting a recipe takes its
  items with it).
- recipe_items.ingredient_product_id FK RESTRICT (ingredients are
  referenced by recipes; protecting them from accidental deletion).

Numeric precision:
- qty is NUMERIC(10,3) — 7 digits before decimal + 3 after.
  Supports 1234567.890. Covers large batch recipes (e.g. punch
  recipes measuring in liters) and fine pours (0.5ml bitters).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e1_add_recipes"
down_revision: str | None = "d1_add_bar_stock"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ─── recipes (header) ─────────────────────────────────────────────────────
    op.create_table(
        "recipes",
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
        sa.Column(
            "drink_product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "yield_qty",
            sa.Numeric(10, 3),
            nullable=False,
            server_default=sa.text("1"),
            comment="How much this recipe produces in yield_unit",
        ),
        sa.Column(
            "yield_unit",
            postgresql.ENUM(name="product_unit", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "notes",
            sa.Text,
            nullable=True,
            comment="Bartender instructions, technique notes, variations.",
        ),
        sa.CheckConstraint(
            "yield_qty > 0",
            name="recipes_yield_positive",
        ),
    )

    op.create_index("ix_recipes_drink_product_id", "recipes", ["drink_product_id"])

    # One recipe per (tenant, drink)
    op.create_index(
        "uq_recipes_tenant_drink",
        "recipes",
        ["tenant_id", "drink_product_id"],
        unique=True,
    )

    # ─── recipe_items (lines) ─────────────────────────────────────────────────
    op.create_table(
        "recipe_items",
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
        sa.Column(
            "recipe_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingredient_product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "qty",
            sa.Numeric(10, 3),
            nullable=False,
        ),
        sa.Column(
            "unit",
            postgresql.ENUM(name="product_unit", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "note",
            sa.Text,
            nullable=True,
            comment="Per-ingredient note, e.g. 'freshly squeezed' or 'muddled'.",
        ),
        sa.CheckConstraint(
            "qty > 0",
            name="recipe_items_qty_positive",
        ),
    )

    op.create_index("ix_recipe_items_recipe_id", "recipe_items", ["recipe_id"])
    op.create_index(
        "ix_recipe_items_ingredient_product_id",
        "recipe_items",
        ["ingredient_product_id"],
    )

    # No duplicate ingredient within a single recipe
    op.create_index(
        "uq_recipe_items_recipe_ingredient",
        "recipe_items",
        ["recipe_id", "ingredient_product_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_recipe_items_recipe_ingredient", table_name="recipe_items")
    op.drop_index("ix_recipe_items_ingredient_product_id", table_name="recipe_items")
    op.drop_index("ix_recipe_items_recipe_id", table_name="recipe_items")
    op.drop_table("recipe_items")

    op.drop_index("uq_recipes_tenant_drink", table_name="recipes")
    op.drop_index("ix_recipes_drink_product_id", table_name="recipes")
    op.drop_table("recipes")
