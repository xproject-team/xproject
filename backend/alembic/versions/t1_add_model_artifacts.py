"""add model_artifacts table for the MLOps version + rollback loop

Revision ID: t1_add_model_artifacts
Revises: s1_add_scan_void_columns
Create Date: 2026-05-27

The MLOps foundation table.  Tracks every trained model artifact across
all tenants with version, training metadata, and active/inactive state.

Architecture (locked 2026-05-27 with Hesam):
  Pattern         A — offline retrain after each event ends
  Trigger         event.status -> ENDED fires an arq retrain job
  Versioning      this table + .joblib files on disk
  Promotion       latest is auto-promoted; rollback via CLI
  Visibility      CLI for now, no Omar-facing UI yet
  Scope           per-tenant models

Two rows per tenant once live: one for "model_a_revenue", one for
"model_a_category".  Future Model B / Model C reuse the same table
without schema changes.

Key invariants enforced at the DB layer:
  - UNIQUE (tenant_id, model_name, version)
    Versions never collide; rollback to a specific version is unambiguous.
  - At most one is_active=TRUE per (tenant_id, model_name)
    Enforced via a partial unique index — bugs cannot ship two active
    models for the same tenant + model_name.

Cascade behavior:
  - tenants -> ON DELETE CASCADE
    If a tenant is deleted, their artifacts go too.  The .joblib files
    on disk are cleaned up separately by a janitor task (deferred work).
  - events -> ON DELETE SET NULL
    If the triggering event is deleted, the artifact survives, just
    loses its provenance link.

Backfill:
  This migration creates the table empty.  The seed model trained from
  CSV historicals is inserted by the backfill script (P2.MLO.2), not
  by this migration.  Migrations stay reversible and idempotent.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "t1_add_model_artifacts"
down_revision = "s1_add_scan_void_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_artifacts",
        # ─── Identity ──────────────────────────────────────────────
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
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),

        # ─── Artifact file on disk ─────────────────────────────────
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_sha256", sa.Text(), nullable=False),

        # ─── Training metadata ─────────────────────────────────────
        sa.Column(
            "trained_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "training_event_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::UUID[]"),
        ),
        sa.Column("n_training_events", sa.Integer(), nullable=False),
        sa.Column("n_training_rows", sa.Integer(), nullable=False),
        sa.Column(
            "feature_names",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::TEXT[]"),
        ),
        sa.Column("algorithm", sa.Text(), nullable=False),
        sa.Column(
            "metrics_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),

        # ─── Promotion state ───────────────────────────────────────
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),

        # ─── Audit ─────────────────────────────────────────────────
        sa.Column("triggered_by", sa.Text(), nullable=False),
        sa.Column(
            "triggered_by_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="SET NULL"),
            nullable=True,
        ),

        sa.UniqueConstraint(
            "tenant_id", "model_name", "version",
            name="uq_model_artifacts_tenant_model_version",
        ),
    )

    # Partial unique index: enforces at most one active version per
    # (tenant_id, model_name).  The DB rejects any commit that would
    # create a second active row for the same pair.
    op.create_index(
        "uq_model_artifacts_one_active_per_model",
        "model_artifacts",
        ["tenant_id", "model_name"],
        unique=True,
        postgresql_where=sa.text("is_active = TRUE"),
    )

    # Fast lookup for predict-time queries: "give me the active artifact
    # for this tenant + model_name".  Covers the hot path.
    op.create_index(
        "idx_model_artifacts_active_lookup",
        "model_artifacts",
        ["tenant_id", "model_name"],
        postgresql_where=sa.text("is_active = TRUE"),
    )

    # Fast lookup for version-history listing: "give me all versions
    # of this model for this tenant, newest first".  Covers the CLI.
    op.create_index(
        "idx_model_artifacts_version_history",
        "model_artifacts",
        ["tenant_id", "model_name", sa.text("version DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_model_artifacts_version_history", table_name="model_artifacts")
    op.drop_index("idx_model_artifacts_active_lookup", table_name="model_artifacts")
    op.drop_index("uq_model_artifacts_one_active_per_model", table_name="model_artifacts")
    op.drop_table("model_artifacts")
