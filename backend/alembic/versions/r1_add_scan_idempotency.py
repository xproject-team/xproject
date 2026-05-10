"""add client_event_id to warehouse_scans for idempotent retries

Revision ID: r1_add_scan_idempotency
Revises: q1_add_product_barcode
Create Date: 2026-05-09

Adds the client-generated UUID idempotency key. Critical Sundance-safety
change: every scan submission now carries a client_event_id UUID generated
at the moment of the scan event (camera detection or manual submit). The
server uses this to dedupe retries.

Failure modes this prevents:
  - Operator's phone has a network blip → frontend retries → backend
    detects same client_event_id → returns existing scan, no double count
  - Camera fires multiple recognitions for one bottle in <500ms → frontend
    debounces, but if it slips through the server still dedupes
  - Browser tab restarts mid-scan → operator re-scans the same bottle →
    same UUID generated client-side from a queued localStorage entry
    → server returns existing row

Schema change:
  - client_event_id  UUID  NULL

Constraints:
  - UNIQUE partial index ix_warehouse_scans_client_event_id on
    (tenant_id, client_event_id) WHERE client_event_id IS NOT NULL
  - Per-tenant unique. Multi-tenant safe.
  - Partial: NULL never collides. Old scans (no UUID) are unaffected.

Backward compatibility:
  - Existing rows: client_event_id = NULL. Untouched.
  - Old API clients (no UUID): backend still accepts the scan, just no
    dedup protection. Frontend will be updated in Step 6.4 to always send.

Spec: docs/scanner-architecture.md Sundance-safety principle #4 (idempotency).
"""
from alembic import op
import sqlalchemy as sa


revision = "r1_add_scan_idempotency"
down_revision = "q1_add_product_barcode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "warehouse_scans",
        sa.Column("client_event_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_warehouse_scans_client_event_id",
        "warehouse_scans",
        ["tenant_id", "client_event_id"],
        unique=True,
        postgresql_where=sa.text("client_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_warehouse_scans_client_event_id", table_name="warehouse_scans")
    op.drop_column("warehouse_scans", "client_event_id")
