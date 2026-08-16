"""alerts — add manual resolve (resolved_at / resolved_by_user_id).

Revision ID: ag1
Revises: af1
Create Date: 2026-08-17

The schema had no way to distinguish a human manually resolving an alert
(because they fixed the underlying condition outside the platform — e.g.
mapping a Slesh shop to a bar via direct DB work) from the system
auto-resolving it (because a detector re-evaluated and the condition no
longer holds). Reusing auto_resolved_at for a manual action would be
factually wrong — the column's own docstring says "System resolved it;
Owner didn't need to act" — and would corrupt the post-event report
narrative, which relies on these timestamps to reconstruct who did what.

acknowledged_at already exists but means something different ("Owner has
seen this and is on it") — not "the underlying condition is over". An
alert can be resolved without ever having been acknowledged (exactly the
2 August unmapped-shop case: nobody clicked Acknowledge, the mapping was
just fixed directly in the database).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ag1"
down_revision = "af1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column(
            "resolved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("alerts", "resolved_by_user_id")
    op.drop_column("alerts", "resolved_at")
