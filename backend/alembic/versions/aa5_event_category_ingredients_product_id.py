"""event_category_ingredients.product_id — FK to products, replacing
free-text slesh_category as the depletion-engine join key.

Revision ID: aa5
Revises: aa4
Create Date: 2026-07-12

Root cause of the Sundance Jul-5 depletion outage: the service layer
joined stock_transactions to event_category_ingredients by matching
free-text slesh_category against product.name — two independently
maintained string namespaces that silently drifted apart, zeroing out
consumed_ml for hours.

This migration adds product_id nullable so a backfill script
(app/scripts/backfill_recipe_product_id.py) can resolve existing rows
before a follow-up migration makes it NOT NULL. slesh_category stays
NOT NULL for now — it is not dropped until the service code cuts over
to product_id (tracked as a later sprint item).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID


revision = "aa5"
down_revision = "aa4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "event_category_ingredients",
        sa.Column("product_id", PgUUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "event_category_ingredients_product_id_fkey",
        "event_category_ingredients",
        "products",
        ["product_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_event_cat_ing_product_id",
        "event_category_ingredients",
        ["product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_cat_ing_product_id", table_name="event_category_ingredients")
    op.drop_constraint(
        "event_category_ingredients_product_id_fkey",
        "event_category_ingredients",
        type_="foreignkey",
    )
    op.drop_column("event_category_ingredients", "product_id")
