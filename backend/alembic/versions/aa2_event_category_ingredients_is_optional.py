"""event_category_ingredients.is_optional — alcohol-base vs mixer flag.

Revision ID: aa2
Revises: aa1
Create Date: 2026-07-01

false = required alcohol base (blocks depletion math if missing).
true  = optional mixer/extra (cola, tonic, syrup — tracked but not
        required for the drink to fire depletion). The alerts engine
        treats both identically; the flag only drives FE section
        grouping (Catalog page's per-event recipe editor, Chunk 2).
"""
from alembic import op
import sqlalchemy as sa


revision = "aa2"
down_revision = "aa1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "event_category_ingredients",
        sa.Column(
            "is_optional", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("event_category_ingredients", "is_optional")
