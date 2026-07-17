"""event_category_ingredients.product_id — enforce NOT NULL.

Revision ID: aa6
Revises: aa5
Create Date: 2026-07-17

Follow-up to aa5. The service layer (bar_supplier_stock_service.py) now
reads product_id exclusively, and the backfill script has resolved every
row. This migration is NOT run as part of Day 3 dev work — it is deferred
until Day 2's production backfill confirms 100% coverage on prod, since
applying it against any row still NULL would fail outright.
"""
from alembic import op


revision = "aa6"
down_revision = "aa5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "event_category_ingredients", "product_id", nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "event_category_ingredients", "product_id", nullable=True,
    )
