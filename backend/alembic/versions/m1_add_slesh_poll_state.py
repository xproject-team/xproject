"""add slesh_poll_state table (Slesh polling cursor)

Revision ID: m1_add_slesh_poll_state
Revises: l1_add_pos_id_to_products
Create Date: 2026-05-02

Tracks the polling worker's progress against Slesh's order stream so the
worker knows how far back to ask on the next cycle. One row per
(tenant_id, brand_id, experience_id) scope.

Why this lives in the DB and not in Redis:
- Survives Redis restarts / cache evictions
- Visible to ops via psql for debugging during Sundance
- Atomic with the order ingestion in the same transaction
- Slesh data is small (one row per event); no scaling concern

Spec: docs/slesh-integration-roadmap.md §B6.2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "m1_add_slesh_poll_state"
down_revision: Union[str, None] = "l1_add_pos_id_to_products"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "slesh_poll_state",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "brand_id",
            sa.String(length=128),
            nullable=False,
            comment="Slesh brand _id this cursor is for",
        ),
        sa.Column(
            "experience_id",
            sa.String(length=128),
            nullable=True,
            comment="Slesh experience _id (event scope); NULL means brand-wide",
        ),
        sa.Column(
            "last_seen_ts",
            sa.BigInteger(),
            nullable=False,
            comment="High-water mark — Unix ms of the most recent _createdAt we ingested",
        ),
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the poller last fired against this scope",
        ),
        sa.Column(
            "last_status",
            sa.String(length=32),
            nullable=True,
            comment="ok | error | circuit_open — diagnostic for ops",
        ),
        sa.Column(
            "last_error",
            sa.Text(),
            nullable=True,
            comment="Truncated error message from the most recent failure (NULL on success)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
    )

    # At most one cursor per (tenant, brand, experience) scope.
    # NULL experience_id forms its own bucket — the brand-wide cursor.
    op.create_index(
        "ix_slesh_poll_state_scope",
        "slesh_poll_state",
        ["tenant_id", "brand_id", "experience_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_slesh_poll_state_scope", table_name="slesh_poll_state")
    op.drop_table("slesh_poll_state")
