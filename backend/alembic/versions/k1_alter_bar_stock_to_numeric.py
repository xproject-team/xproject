"""alter bar_stock quantity columns from INTEGER to NUMERIC(12, 3)

Revision ID: k1_alter_bar_stock_to_numeric
Revises: j1_add_warehouse
Create Date: 2026-04-25

Brings bar_stock.{allocated,current,returned}_qty in line with the rest
of the system. Every other quantity column in the schema is NUMERIC(12, x)
to support partial bottle pours, partial cases, and decimal stock counts:

  stock_transactions.qty           NUMERIC(12, 3)
  warehouse_inventory.current_qty  NUMERIC(12, 2)
  warehouse_allocations.reserved_qty NUMERIC(12, 2)
  warehouse_scans.qty              NUMERIC(12, 2)

bar_stock was the outlier — INTEGER, silently truncating fractional
consumption into integer counts. Closes T1.9 from docs/roadmap.md.

Postgres handles INT -> NUMERIC widening cleanly (no data loss). The
five existing CHECK constraints survive automatically; no recreate.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "k1_alter_bar_stock_to_numeric"
down_revision = "j1_add_warehouse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NUMERIC(12, 3) matches stock_transactions.qty for arithmetic
    # consistency. 12 total digits, 3 decimal places — handles any
    # realistic hospitality quantity (max ~999,999,999.999).
    for column in ("allocated_qty", "current_qty", "returned_qty"):
        op.alter_column(
            "bar_stock",
            column,
            type_=sa.Numeric(12, 3),
            postgresql_using=f"{column}::numeric(12, 3)",
            existing_nullable=False,
        )


def downgrade() -> None:
    # Reverse: cast back to INTEGER. Will silently truncate any
    # fractional values that landed during the NUMERIC window —
    # acceptable for a downgrade, since downgrades are explicit.
    for column in ("allocated_qty", "current_qty", "returned_qty"):
        op.alter_column(
            "bar_stock",
            column,
            type_=sa.Integer(),
            postgresql_using=f"{column}::integer",
            existing_nullable=False,
        )
