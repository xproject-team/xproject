"""add user_roles join table for multi-role auth

Revision ID: p1_add_user_roles_table
Revises: o4_extend_recipes_with_template
Create Date: 2026-05-07

Adds the `user_roles` join table to support a single user being authorized
for multiple roles.

Schema:
  - id                    UUID PK
  - user_id               UUID FK → users.id (CASCADE)
  - role                  user_role enum (REUSED, not recreated)
  - assigned_at           TIMESTAMPTZ
  - assigned_by_user_id   UUID FK → users.id (SET NULL)

Constraints:
  - UNIQUE (user_id, role)
  - INDEX  (user_id)

Backfill:
  Every existing user gets one user_roles row matching their current users.role.
  assigned_by_user_id is NULL (system-assigned during migration).

Backward compatibility:
  Does NOT touch the existing users.role column. Phase 1D drops it later.

Spec: docs/sundance-readiness-roadmap.md (Phase 1A — Add multi-role schema).

Notes on enum reuse:
  We use postgresql.ENUM with create_type=False (NOT sa.Enum). The plain
  sa.Enum form has a known issue where the table-creation event fires a
  duplicate CREATE TYPE statement, ignoring the create_type=False flag.
  postgresql.ENUM honors the flag at every code path.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.dialects.postgresql import ENUM as PgEnum


revision: str = "p1_add_user_roles_table"
down_revision: Union[str, None] = "o4_extend_recipes_with_template"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ─── Reference to the EXISTING user_role enum ───────────────────────────
# create_type=False tells SQLAlchemy: "this enum is already in the database
# (created by 960521bf64a4_initial_*.py); do NOT try to CREATE it again."
# Using postgresql.ENUM (not sa.Enum) ensures this flag is respected
# at table-creation time as well as at column-creation time.
user_role_enum = PgEnum(
    "OWNER", "MANAGER", "BARTENDER", "WAREHOUSE",
    name="user_role",
    create_type=False,
)


def upgrade() -> None:
    # ── Create the user_roles join table ─────────────────────────────────
    op.create_table(
        "user_roles",
        sa.Column(
            "id",
            PgUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            comment="The user this role assignment belongs to. CASCADE on user delete.",
        ),
        sa.Column(
            "role",
            user_role_enum,
            nullable=False,
            comment="The role this user is authorized to act as. Reuses existing user_role enum.",
        ),
        sa.Column(
            "assigned_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="When this role was granted. Audit trail.",
        ),
        sa.Column(
            "assigned_by_user_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment=(
                "Owner who granted this role. NULL for rows created by the "
                "initial backfill (system-assigned)."
            ),
        ),
        sa.UniqueConstraint("user_id", "role", name="uq_user_roles_user_id_role"),
    )

    op.create_index(
        "ix_user_roles_user_id",
        "user_roles",
        ["user_id"],
        unique=False,
    )

    # ── Backfill ─────────────────────────────────────────────────────────
    op.execute(
        """
        INSERT INTO user_roles (id, user_id, role, assigned_at, assigned_by_user_id)
        SELECT
            gen_random_uuid(),
            u.id,
            u.role,
            now(),
            NULL
        FROM users u
        ON CONFLICT (user_id, role) DO NOTHING
        """
    )


def downgrade() -> None:
    # Drop the index and table. We do NOT drop the user_role enum — it
    # predates this migration and is still used by users.role.
    op.drop_index("ix_user_roles_user_id", table_name="user_roles")
    op.drop_table("user_roles")
