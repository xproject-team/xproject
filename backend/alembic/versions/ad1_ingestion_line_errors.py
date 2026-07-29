"""ingestion_line_errors — durable per-line ingestion failure trace

Revision ID: ad1
Revises: ac1
Create Date: 2026-07-29

Hardening item from the Phase 2 zero-line-order investigation: 517 of
Jul-5's zero-line orders (real products, confirmed status, correctly
mapped bars) have no remaining explanation and no trace anywhere in our
data — order_ingester's per-line exception handler only ever appended
to IngestResult.error_messages, an in-memory value read once by the
poller for logging and then discarded forever.

This table gives the next occurrence a queryable trace instead. Written
by a FRESH, independent session at the moment of failure (see
order_ingester.py::_persist_line_error) so it survives even if the
failure itself left the ingesting order's transaction unusable, and
wrapped in its own try/except so a failure to log can never cause a
second failure in the ingestion path itself.

Deliberately minimal: no dashboard, no alert wiring, no foreign key
into event_orders (the order may not have persisted a row at all,
depending on where in ingest_order() the failure happened) — just
event_id, tenant_id, and the raw identifiers/error text needed to
`select * from ingestion_line_errors where event_id = ...` after the
fact.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ad1"
down_revision = "ac1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_line_errors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                   server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slesh_order_id", sa.String(64), nullable=False),
        sa.Column("slesh_line_id", sa.String(64), nullable=False),
        sa.Column("error_type", sa.String(128), nullable=False),
        sa.Column("error_message", sa.Text, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ingestion_line_errors_event_id", "ingestion_line_errors", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_line_errors_event_id", table_name="ingestion_line_errors")
    op.drop_table("ingestion_line_errors")
