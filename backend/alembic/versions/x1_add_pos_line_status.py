"""add pos_line_status to stock_transactions

Mirror the live ALTER TABLE applied during Sundance 14 cleanup
(2026-06-15). Differentiates Slesh confirmed sales from refunded
lines so aggregation queries exclude refunds from revenue.

Revision ID: x1_add_pos_line_status
Revises: y3_event_category_ingredients, u1_event_scheduled_at, k1_alter_bar_stock_to_numeric, a9_event_version
"""
from alembic import op

revision = 'x1_add_pos_line_status'
down_revision = (
    'y3_event_category_ingredients',
    'u1_event_scheduled_at',
    'k1_alter_bar_stock_to_numeric',
    'a9_event_version',
)
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE stock_transactions
        ADD COLUMN IF NOT EXISTS pos_line_status TEXT
        NOT NULL DEFAULT 'confirmed'
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_stock_tx_line_status
        ON stock_transactions(pos_line_status)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_stock_tx_line_status")
    op.execute("ALTER TABLE stock_transactions DROP COLUMN IF EXISTS pos_line_status")
