"""Add scheduled_date + version to events; one-live-per-tenant unique index.

Revision ID: a9_event_version
Revises: a8_add_message_search
Create Date: 2026-04-16

Changes:
  1. events.scheduled_date  DATE NOT NULL
  2. events.version         INTEGER NOT NULL DEFAULT 1
  3. partial unique index   ON events(tenant_id) WHERE status = \'live\'
"""
from alembic import op
import sqlalchemy as sa


revision = "a9_event_version"
down_revision = "a8_add_message_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add scheduled_date as NULLABLE, backfill, then NOT NULL
    op.add_column(
        "events",
        sa.Column("scheduled_date", sa.Date(), nullable=True),
    )
    op.execute(
        "UPDATE events SET scheduled_date = created_at::date WHERE scheduled_date IS NULL"
    )
    op.alter_column("events", "scheduled_date", nullable=False)

    # 2. Add version column with default 1
    op.add_column(
        "events",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    # 3. Defensive check: ensure no tenant has >1 live event
    op.execute("""
        DO $$
        DECLARE
            violator_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO violator_count FROM (
                SELECT tenant_id FROM events WHERE status = 'LIVE'
                GROUP BY tenant_id HAVING COUNT(*) > 1
            ) t;
            IF violator_count > 0 THEN
                RAISE EXCEPTION
                    'Cannot create one_live_event_per_tenant index: % tenant(s) have multiple live events. Manual cleanup required.',
                    violator_count;
            END IF;
        END $$;
    """)

    # 4. Create partial unique index
    op.create_index(
        "one_live_event_per_tenant",
        "events",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'LIVE'"),
    )


def downgrade() -> None:
    op.drop_index("one_live_event_per_tenant", table_name="events")
    op.drop_column("events", "version")
    op.drop_column("events", "scheduled_date")
