"""eo2 add created_at + updated_at to event_orders

TenantScopedModel (which EventOrder inherits) declares created_at
and updated_at columns. The original eo1 migration created the
table without these, so ORM INSERTs fail with "column does not
exist" and the transaction aborts. This migration adds them.

Revision ID: eo2_event_orders_timestamps
Revises: eo1_add_event_orders
Create Date: 2026-06-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "eo2_event_orders_timestamps"
down_revision = "eo1_add_event_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "event_orders",
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "event_orders",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("event_orders", "updated_at")
    op.drop_column("event_orders", "created_at")
