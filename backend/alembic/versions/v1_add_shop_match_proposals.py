"""Add slesh_shop_match_proposals table.

Revision ID: v1_add_shop_match_proposals
Revises: u1_event_scheduled_at
Create Date: 2026-06-01

S4 of the e2e validation build (docs/e2e-validation-design.md).
Stores PENDING matches between Slesh shop IDs and existing bars.
Owner approves/rejects/skips each before the linkage is persisted
on the bar.

Design B (Omar approved 2026-06-01): don't auto-link, don't auto-
create new bars. Surface every unmatched Slesh shop as a proposal
with a fuzzy-match suggestion, let the owner decide.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "v1_add_shop_match_proposals"
down_revision: Union[str, None] = "u1_event_scheduled_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Status enum ──────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE shop_match_status AS ENUM "
        "('PENDING', 'ACCEPTED', 'REJECTED', 'SKIPPED')"
    )

    # ── Table ────────────────────────────────────────────────────────
    op.create_table(
        "slesh_shop_match_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id",  postgresql.UUID(as_uuid=True), nullable=False),

        # Snapshot of the Slesh shop at proposal-creation time.
        sa.Column("slesh_shop_id",   sa.String(64),  nullable=False),
        sa.Column("slesh_shop_name", sa.String(255), nullable=False),

        # The bar we think this shop maps to (best fuzzy match).
        # Nullable: there may be no candidate bar above threshold,
        # in which case the owner must create a new bar OR reject.
        sa.Column("suggested_bar_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("similarity_score", sa.Numeric(4, 3), nullable=False,
                  server_default=sa.text("0.000")),

        # Decision state machine.
        sa.Column("status", postgresql.ENUM(
            "PENDING", "ACCEPTED", "REJECTED", "SKIPPED",
            name="shop_match_status", create_type=False,
        ), nullable=False, server_default="PENDING"),

        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),

        # Timestamps.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),

        # FKs.
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"],  ["events.id"],  ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["suggested_bar_id"], ["bars.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )

    # ── Indexes ──────────────────────────────────────────────────────
    # One proposal per (tenant, event, slesh shop). Re-running the
    # cron must NOT create duplicate proposals for the same shop.
    op.create_index(
        "uq_slesh_shop_match_proposals_tenant_event_shop",
        "slesh_shop_match_proposals",
        ["tenant_id", "event_id", "slesh_shop_id"],
        unique=True,
    )

    # Hot path: list pending proposals for an event\'s approval UI.
    op.create_index(
        "ix_slesh_shop_match_proposals_pending",
        "slesh_shop_match_proposals",
        ["tenant_id", "event_id", "status"],
    )

    # CHECK: similarity in [0, 1].
    op.create_check_constraint(
        "ck_slesh_shop_match_proposals_similarity_range",
        "slesh_shop_match_proposals",
        "similarity_score >= 0 AND similarity_score <= 1",
    )

    # CHECK: decided_at NOT NULL iff status != pending. Prevents
    # forgetting to stamp the decision time.
    op.create_check_constraint(
        "ck_slesh_shop_match_proposals_decided_at_consistent",
        "slesh_shop_match_proposals",
        "(status = 'PENDING' AND decided_at IS NULL) "
        "OR (status != 'PENDING' AND decided_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_slesh_shop_match_proposals_pending",
        table_name="slesh_shop_match_proposals",
    )
    op.drop_index(
        "uq_slesh_shop_match_proposals_tenant_event_shop",
        table_name="slesh_shop_match_proposals",
    )
    op.drop_table("slesh_shop_match_proposals")
    op.execute("DROP TYPE shop_match_status")
