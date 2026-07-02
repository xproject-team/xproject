"""events.is_training_eligible — ML training-set contamination guard.

Revision ID: aa3
Revises: aa2
Create Date: 2026-07-02

Phase F's nowcast auto-retrain (predictions/nowcast/retrain.py) pulls
every COMPLETED event into the training parquet with no way to tell a
real Sundance event apart from simulation/test/seed data. The dev DB
already has 16 pre-existing COMPLETED events, most named "Sundance 14
— SIMULATION" or similar test fixtures — if retrain ever ran for real,
it would silently corrupt the production training set with synthetic
data.

default=true (every event is training-eligible unless flagged
otherwise) — the backfill below flips known-bad names to false. Match
is intentionally broad (substring, case-insensitive) since false
positives just mean "one fewer training event," while false negatives
mean contaminated training data — the asymmetry favors over-excluding.
"""
from alembic import op
import sqlalchemy as sa


revision = "aa3"
down_revision = "aa2"
branch_labels = None
depends_on = None

_EXCLUDE_SUBSTRINGS = ("SIMULATION", "TEST", "SMOKE", "EXAMPLE", "TRIM")


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "is_training_eligible", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
    )

    conn = op.get_bind()
    where_clause = " OR ".join(
        f"name ILIKE :pat_{i}" for i in range(len(_EXCLUDE_SUBSTRINGS))
    )
    params = {
        f"pat_{i}": f"%{s}%" for i, s in enumerate(_EXCLUDE_SUBSTRINGS)
    }
    conn.execute(
        sa.text(f"UPDATE events SET is_training_eligible = false WHERE {where_clause}"),
        params,
    )


def downgrade() -> None:
    op.drop_column("events", "is_training_eligible")
