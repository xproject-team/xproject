"""add reports table

Revision ID: h1_add_reports
Revises: g1_add_alerts
Create Date: 2026-04-22 14:40:00.000000

Post-event report storage. See docs/report-module-spec.md section 4.1.

Creates:
  - enum `reportstatus`    : pending, generating, ready, failed
  - enum `reportlanguage`  : it, en
  - table `reports`        : one row per (event, version, language)
  - 3 indexes (one UNIQUE)
  - 1 CHECK constraint (no self-supersede)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "h1_add_reports"
down_revision = "g1_add_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- Enum types --
    report_status = postgresql.ENUM(
        "pending", "generating", "ready", "failed",
        name="reportstatus",
        create_type=False,
    )
    report_language = postgresql.ENUM(
        "it", "en",
        name="reportlanguage",
        create_type=False,
    )
    report_status.create(op.get_bind(), checkfirst=True)
    report_language.create(op.get_bind(), checkfirst=True)

    # -- reports table --
    op.create_table(
        "reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "superseded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", report_status, nullable=False, server_default="pending"),
        sa.Column("language", report_language, nullable=False),
        sa.Column("data_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pdf_bytes", postgresql.BYTEA(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "generated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "superseded_by IS NULL OR id != superseded_by",
            name="ck_reports_no_self_supersede",
        ),
    )

    # -- Indexes --
    op.create_index(
        "ix_reports_tenant_event_version_language",
        "reports",
        ["tenant_id", "event_id", "version", "language"],
        unique=True,
    )
    op.create_index(
        "ix_reports_tenant_event_status",
        "reports",
        ["tenant_id", "event_id", "status"],
    )
    op.create_index(
        "ix_reports_tenant_status_generated_at",
        "reports",
        ["tenant_id", "status", sa.text("generated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_reports_tenant_status_generated_at", table_name="reports")
    op.drop_index("ix_reports_tenant_event_status", table_name="reports")
    op.drop_index("ix_reports_tenant_event_version_language", table_name="reports")
    op.drop_table("reports")

    # Drop enum types AFTER the table using them is gone
    postgresql.ENUM(name="reportlanguage").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="reportstatus").drop(op.get_bind(), checkfirst=True)
