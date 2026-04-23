"""add predictions table

Revision ID: i1_add_predictions
Revises: h1_add_reports
Create Date: 2026-04-23 14:30:00.000000

Demand prediction storage. See docs/predictions-module-spec.md section 4.1.

Creates:
  - enum `predictionstatus`   : pending, generating, ready, failed, insufficient_data
  - enum `predictortype`      : heuristic, ml
  - enum `confidencetier`     : low, medium, high
  - table `predictions`       : one row per (event, version)
  - 3 indexes (one UNIQUE)
  - 1 CHECK constraint (no self-supersede)

Inherits id, tenant_id, created_at, updated_at from TenantScopedModel pattern
(declared explicitly here; model uses the base class for the columns).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "i1_add_predictions"
down_revision = "h1_add_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- Enum types --
    prediction_status = postgresql.ENUM(
        "pending", "generating", "ready", "failed", "insufficient_data",
        name="predictionstatus",
        create_type=False,
    )
    predictor_type = postgresql.ENUM(
        "heuristic", "ml",
        name="predictortype",
        create_type=False,
    )
    confidence_tier = postgresql.ENUM(
        "low", "medium", "high",
        name="confidencetier",
        create_type=False,
    )
    prediction_status.create(op.get_bind(), checkfirst=True)
    predictor_type.create(op.get_bind(), checkfirst=True)
    confidence_tier.create(op.get_bind(), checkfirst=True)

    # -- predictions table --
    op.create_table(
        "predictions",
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
            sa.ForeignKey("predictions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", prediction_status, nullable=False, server_default="pending"),
        sa.Column("predictor_type", predictor_type, nullable=False, server_default="heuristic"),
        sa.Column("data_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("based_on_event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence_tier", confidence_tier, nullable=False, server_default="low"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "generated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("insufficient_data_message", sa.Text(), nullable=True),
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
            name="ck_predictions_no_self_supersede",
        ),
    )

    # -- Indexes --
    # Matches TenantScopedModel.tenant_id(index=True)
    op.create_index(
        "ix_predictions_tenant_id",
        "predictions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_predictions_tenant_event_version",
        "predictions",
        ["tenant_id", "event_id", "version"],
        unique=True,
    )
    op.create_index(
        "ix_predictions_tenant_event_status",
        "predictions",
        ["tenant_id", "event_id", "status"],
    )
    op.create_index(
        "ix_predictions_tenant_status_generated_at",
        "predictions",
        ["tenant_id", "status", sa.text("generated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_predictions_tenant_status_generated_at", table_name="predictions")
    op.drop_index("ix_predictions_tenant_event_status", table_name="predictions")
    op.drop_index("ix_predictions_tenant_event_version", table_name="predictions")
    op.drop_index("ix_predictions_tenant_id", table_name="predictions")
    op.drop_table("predictions")

    postgresql.ENUM(name="confidencetier").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="predictortype").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="predictionstatus").drop(op.get_bind(), checkfirst=True)
