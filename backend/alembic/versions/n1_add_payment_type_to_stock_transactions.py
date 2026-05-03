"""add payment_type to stock_transactions

Revision ID: n1_add_payment_type
Revises: m1_add_slesh_poll_state
Create Date: 2026-05-03

Adds payment_type column + index to stock_transactions, plus a native
Postgres ENUM transaction_payment_type. NULLABLE so historical rows
remain valid; backfill script populates them later.

Spec: docs/slesh-integration-roadmap.md §B8b.2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n1_add_payment_type"
down_revision: Union[str, None] = "m1_add_slesh_poll_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ENUM values — match Slesh\'s payment.type vocabulary 1:1, with one
# rename: \'tap-to-pay\' \u2192 \'tap_to_pay\' (Postgres ENUMs cannot contain hyphens).
PAYMENT_TYPE_ENUM = sa.Enum(
    "stripe",
    "adyen",
    "token",
    "cash",
    "card",
    "tap_to_pay",
    "mixed",
    name="transaction_payment_type",
    create_type=True,
)


def upgrade() -> None:
    PAYMENT_TYPE_ENUM.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "stock_transactions",
        sa.Column(
            "payment_type",
            PAYMENT_TYPE_ENUM,
            nullable=True,
            comment=(
                "Slesh payment.type. NULL for rows ingested before B8b "
                "migration; backfill script populates retroactively."
            ),
        ),
    )
    op.create_index(
        "ix_stock_transactions_payment_type",
        "stock_transactions",
        ["payment_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stock_transactions_payment_type",
        table_name="stock_transactions",
    )
    op.drop_column("stock_transactions", "payment_type")
    PAYMENT_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)
