"""device_count NOT NULL DEFAULT 0 — fix Phase B w2 nullable landmine

The w2 migration added bars.device_count as nullable with no backfill, so
existing bars held NULL. BarResponse types it as int, which 500'd the
/bars endpoint (and the dashboard) on any pre-existing bar. device_count
is a count — it must never be NULL.

Revision ID: w3_device_count_notnull
Revises: w2_bar_product_slesh
"""
from alembic import op
import sqlalchemy as sa

revision = "w3_device_count_notnull"
down_revision = "w2_bar_product_slesh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE bars SET device_count = 0 WHERE device_count IS NULL")
    op.alter_column(
        "bars", "device_count",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="0",
    )


def downgrade() -> None:
    op.alter_column(
        "bars", "device_count",
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
    )
