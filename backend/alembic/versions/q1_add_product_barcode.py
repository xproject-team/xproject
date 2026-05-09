"""add barcode column to products + unique partial index

Revision ID: q1_add_product_barcode
Revises: p1_add_user_roles_table
Create Date: 2026-05-09

Adds the `barcode` column to `products` so the existing
`ScanService.resolve_barcode()` can do real lookups instead of falling
back to name-match (which never actually matched anything).

Schema change:
  - barcode  VARCHAR(64)  NULL

Constraints:
  - UNIQUE partial index ix_products_barcode_unique on
    (tenant_id, barcode) WHERE barcode IS NOT NULL
  - Per-tenant uniqueness — multi-tenant safe.
  - Partial: NULL barcodes never collide (most non-bottle products
    have no barcode — Fresh Lime, House Mojito, etc.)

Backward compatibility:
  - Existing rows get NULL barcode (additive column).
  - Existing barcode-resolve code uses getattr(Product, "barcode", None)
    so this migration enables it transparently.

Spec: docs/scanner-architecture.md (Phase 6, Step 6.1)
"""
from alembic import op
import sqlalchemy as sa


revision = "q1_add_product_barcode"
down_revision = "p1_add_user_roles_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("barcode", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_products_barcode_unique",
        "products",
        ["tenant_id", "barcode"],
        unique=True,
        postgresql_where=sa.text("barcode IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_products_barcode_unique", table_name="products")
    op.drop_column("products", "barcode")
