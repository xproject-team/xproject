"""replace events.scheduled_date with scheduled_at + scheduled_end_at

Revision ID: u1_event_scheduled_at
Revises: t1_add_model_artifacts
Create Date: 2026-06-01

Why:
  Omar\'s end-to-end flow (locked 2026-06-01) requires:
    1. Owner picks EXACT START TIME (not just date) at event creation
    2. Owner picks EXACT END TIME (used by auto-end cron + 60-min-
       silence heuristic)
    3. Owner can manually go LIVE only in window [start - 1h, start]
    4. arq cron auto-promotes draft -> live at scheduled_at if forgotten
    5. arq cron auto-ends live -> completed if scheduled_end_at passed
       AND no Slesh tx in last 60 min

  The existing `scheduled_date date` column has only day granularity
  and no end-time concept, which can\'t support any of the above.

Backfill strategy:
  Existing rows get scheduled_at = scheduled_date + 19:00:00 (Europe/Rome
  evening default — Sundance starts at 7pm) and scheduled_end_at =
  scheduled_date + 23:00:00 (4-hour default). One row in xproject_dev
  today (Sundance 2026, 2026-06-19) — verified before migration.

  After backfill, both new cols are SET NOT NULL and the old
  scheduled_date column is DROPPED. One-phase migration is safe
  because:
    - dev DB only (no production traffic)
    - code patches for the change land BEFORE this migration is run
    - backup taken at backups/xproject_dev_pre_S2_*.sql
"""
from alembic import op
import sqlalchemy as sa


revision = "u1_event_scheduled_at"
down_revision = "t1_add_model_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add nullable columns first
    op.add_column(
        "events",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("scheduled_end_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. Backfill existing rows
    #    Assume 19:00 start, 4-hour duration (Sundance pattern).
    #    Europe/Rome timezone — explicit in the cast so we don\'t lose it.
    op.execute(
        """
        UPDATE events
        SET
          scheduled_at     = (scheduled_date::timestamp + INTERVAL \'19 hours\')
                             AT TIME ZONE \'Europe/Rome\',
          scheduled_end_at = (scheduled_date::timestamp + INTERVAL \'23 hours\')
                             AT TIME ZONE \'Europe/Rome\'
        WHERE scheduled_at IS NULL OR scheduled_end_at IS NULL
        """
    )

    # 3. Now enforce NOT NULL
    op.alter_column(
        "events",
        "scheduled_at",
        nullable=False,
        existing_type=sa.DateTime(timezone=True),
    )
    op.alter_column(
        "events",
        "scheduled_end_at",
        nullable=False,
        existing_type=sa.DateTime(timezone=True),
    )

    # 4. CHECK constraint: end must be after start (DB-level guard)
    op.create_check_constraint(
        "ck_events_scheduled_end_after_start",
        "events",
        "scheduled_end_at > scheduled_at",
    )

    # 5. Drop the old column
    op.drop_column("events", "scheduled_date")


def downgrade() -> None:
    # 1. Re-add scheduled_date nullable
    op.add_column(
        "events",
        sa.Column("scheduled_date", sa.Date(), nullable=True),
    )

    # 2. Backfill scheduled_date from scheduled_at (lose end + time-of-day)
    op.execute(
        """
        UPDATE events
        SET scheduled_date = scheduled_at::date
        WHERE scheduled_date IS NULL
        """
    )

    # 3. Enforce NOT NULL on the restored column
    op.alter_column(
        "events",
        "scheduled_date",
        nullable=False,
        existing_type=sa.Date(),
    )

    # 4. Drop the CHECK constraint
    op.drop_constraint(
        "ck_events_scheduled_end_after_start",
        "events",
        type_="check",
    )

    # 5. Drop the new columns
    op.drop_column("events", "scheduled_end_at")
    op.drop_column("events", "scheduled_at")
