"""delivery_invoices.event_id — link an invoice to a single event.

Revision ID: aa1
Revises: z1
Create Date: 2026-06-30

Nullable for backwards compatibility with rows created before this
column existed. New code paths always populate it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID


revision = "aa1"
down_revision = "z1_bar_devices_and_recharge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "delivery_invoices",
        sa.Column("event_id", PgUUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "delivery_invoices_event_id_fkey",
        "delivery_invoices",
        "events",
        ["event_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_delivery_invoices_event_id",
        "delivery_invoices",
        ["event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_invoices_event_id", table_name="delivery_invoices")
    op.drop_constraint(
        "delivery_invoices_event_id_fkey", "delivery_invoices", type_="foreignkey",
    )
    op.drop_column("delivery_invoices", "event_id")
