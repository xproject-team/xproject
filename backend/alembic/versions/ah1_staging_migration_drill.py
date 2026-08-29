"""DRILL ARTIFACT — staging migration/rollback rehearsal. Not a feature.

Adds one nullable TEXT column, venues.staging_drill_marker, purely so
the manual migration procedure (apply → verify → downgrade → verify)
can be practised on staging where a mistake costs nothing. Production
runs migrations by hand (the Custom Start Command overrides the
Dockerfile's `alembic upgrade head`), and before this drill the
downgrade path had never been executed anywhere.

Chosen shape, deliberately:
  - venues: the lowest-traffic table in the schema (single-digit rows,
    no hot code path reads beyond name/lat-lon).
  - nullable, no default, no index, no FK: applying it rewrites no
    rows; dropping it loses nothing that was not explicitly written
    into it during the drill.
  - downgrade() is REAL — it drops the column. A pass-stub downgrade
    would make the rollback rehearsal a lie.

Lifecycle: after a successful staging drill this file either ships
everywhere (the column is harmless) or is removed before promotion to
main — the operator decides; docs/migration-drill.md records the
procedure and the decision point.

Filename and revision id MATCH here ('ah1') on purpose. Note the repo
trap this drill teaches: 7 older version files have revision ids that
differ from their filenames — always trust `alembic history`/`alembic
current` output, never the directory listing.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ah1"
down_revision = "ag1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "venues",
        sa.Column("staging_drill_marker", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("venues", "staging_drill_marker")
