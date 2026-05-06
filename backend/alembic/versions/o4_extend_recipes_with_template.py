"""extend recipes with display_name and template_id

Revision ID: o4_extend_recipes_with_template
Revises: o3_add_recipe_templates
Create Date: 2026-05-04

Adds two nullable columns to the existing `recipes` table:
  - display_name   VARCHAR(128)   — bartender-facing label (e.g. "Sundance Long Island")
  - template_id    UUID FK        — optional traceability to a recipe_templates row

Both columns are NULLABLE so historical recipes (without a name or template
binding) remain valid. Foreign key uses ON DELETE SET NULL so deleting a
template doesn\'t cascade-destroy tenant recipes that referenced it.

Spec: docs/slesh-integration-roadmap.md (Phase F - Recipe Library).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID


revision: str = "o4_extend_recipes_with_template"
down_revision: Union[str, None] = "o3_add_recipe_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recipes",
        sa.Column(
            "display_name",
            sa.String(length=128),
            nullable=True,
            comment=(
                "Bartender-facing label for this recipe. NULL = use the drink "
                "Product\'s name. Lets Owners give a meaningful name to their "
                "version of a generic Slesh product (e.g. 'Sundance Long Island' "
                "for the 'Cocktail' Slesh product)."
            ),
        ),
    )
    op.add_column(
        "recipes",
        sa.Column(
            "template_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey(
                "recipe_templates.id",
                ondelete="SET NULL",
                name="fk_recipes_template_id",
            ),
            nullable=True,
            comment=(
                "Optional reference to the IBA template this recipe was built "
                "from. Used for traceability + 'based on Long Island' UI badge. "
                "Deleting a template SETs this NULL — never cascades to recipes."
            ),
        ),
    )
    op.create_index(
        "ix_recipes_template_id",
        "recipes",
        ["template_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_recipes_template_id", table_name="recipes")
    op.drop_constraint("fk_recipes_template_id", "recipes", type_="foreignkey")
    op.drop_column("recipes", "template_id")
    op.drop_column("recipes", "display_name")
