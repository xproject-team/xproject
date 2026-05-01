"""add external_pos_id to products (Slesh linkage)

Revision ID: l1_add_external_pos_id_to_products
Revises: k1_alter_bar_stock_to_numeric
Create Date: 2026-05-01

Adds the `external_pos_id` column to the `products` table — stores the
Slesh `_id` (24-char Mongo ObjectId hex) for each product so the reference-
data sync (B5) and the order-polling worker (B6) can map Slesh products to
our local Product rows.

Mirrors the pattern used by bars.slesh_negozio_id:
  - VARCHAR(128) — generous, accommodates any future ID format change
  - NULLABLE — products predating Slesh sync don't have a linkage yet
  - INDEXED — every order-line ingest looks up product by external_pos_id

Spec: docs/slesh-integration-roadmap.md §B4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l1_add_pos_id_to_products"
down_revision: Union[str, None] = "k1_alter_bar_stock_to_numeric"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "external_pos_id",
            sa.String(length=128),
            nullable=True,
            comment="Slesh product._id (24-char Mongo ObjectId). NULL for products created before Slesh sync.",
        ),
    )
    op.create_index(
        "ix_products_external_pos_id",
        "products",
        ["external_pos_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_products_external_pos_id", table_name="products")
    op.drop_column("products", "external_pos_id")
