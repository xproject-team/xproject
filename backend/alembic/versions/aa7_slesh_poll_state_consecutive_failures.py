"""slesh_poll_state.consecutive_failures — streak counter for polling health.

Revision ID: aa7
Revises: aa6
Create Date: 2026-07-17

Day 4 (Jul-19 sprint): GET /events/{event_id}/polling-health needs a
"< 3 consecutive failures" signal distinct from a single transient error.
record_success() resets this to 0; record_failure() increments it
(see app/modules/pos/poll_state.py).
"""
from alembic import op
import sqlalchemy as sa


revision = "aa7"
down_revision = "aa6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "slesh_poll_state",
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("slesh_poll_state", "consecutive_failures")
