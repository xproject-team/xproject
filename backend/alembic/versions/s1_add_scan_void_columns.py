"""add voided_at + voided_by_user_id to warehouse_scans for scan undo

Revision ID: s1_add_scan_void_columns
Revises: r1_add_scan_idempotency
Create Date: 2026-05-09

The Sundance-safety undo button. Federico the Manager scans the wrong
bottle by accident; he taps Undo within 5 seconds; this column tracks
the undo + the inventory delta is reversed atomically by the service
layer.

Column shape:
  - voided_at         TIMESTAMPTZ NULL — wall clock when undo executed
  - voided_by_user_id UUID NULL FK users(id) — who undid it (could be
    the original scanner OR an Owner)

Backward compatibility:
  - Existing rows: both NULL. Untouched.
  - Reads: a row is "active" iff voided_at IS NULL. Reports / KPIs that
    care about live inventory should filter `WHERE voided_at IS NULL`
    OR rely on the inventory tables (which the void service rolls back).
"""
from alembic import op
import sqlalchemy as sa


revision = "s1_add_scan_void_columns"
down_revision = "r1_add_scan_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "warehouse_scans",
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "warehouse_scans",
        sa.Column(
            "voided_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("warehouse_scans", "voided_by_user_id")
    op.drop_column("warehouse_scans", "voided_at")
