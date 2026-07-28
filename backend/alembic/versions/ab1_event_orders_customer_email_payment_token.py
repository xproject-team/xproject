"""event_orders — customer_email + payment_token columns

Revision ID: ab1
Revises: aa9
Create Date: 2026-07-28

Slesh's order API returns three identity signals per order: `user`,
`_customerEmail`, and `payment._paymentToken`. Until now the adapter
persisted only `user` (as raw_extras.user._id) and silently dropped the
other two. This adds queryable columns for the two dropped fields.

  - customer_email: stronger cross-event anchor than the Mongo user id.
    Normalized (lowercase + trimmed) by the application at write time
    (order_ingester.py), NOT here — this migration only adds the column.
  - payment_token: the physical wristband/card credential behind a
    token-type payment. Comparing it to raw_extras.user._id is the only
    way to learn whether one band = one person or a shared group wallet.

Both are NULL for guests who paid cash or never registered — that is
the expected, common case, not an error state.

raw_extras is untouched and remains the full record; these columns exist
so the two fields can be indexed and joined on directly.
"""
from alembic import op
import sqlalchemy as sa


revision = "ab1"
down_revision = "aa9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "event_orders",
        sa.Column("customer_email", sa.Text(), nullable=True),
    )
    op.add_column(
        "event_orders",
        sa.Column("payment_token", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_event_orders_customer_email", "event_orders", ["customer_email"],
    )
    op.create_index(
        "ix_event_orders_payment_token", "event_orders", ["payment_token"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_orders_payment_token", table_name="event_orders")
    op.drop_index("ix_event_orders_customer_email", table_name="event_orders")
    op.drop_column("event_orders", "payment_token")
    op.drop_column("event_orders", "customer_email")
