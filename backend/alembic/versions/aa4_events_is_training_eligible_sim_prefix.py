"""events.is_training_eligible — extend backfill to catch "Sim " prefix.

Revision ID: aa4
Revises: aa3
Create Date: 2026-07-02

Follow-up to aa3. Investigated the one flagged gap: "Sim Sundance
2025-06-15" (id=2e7a68c0-a306-40b2-8a00-d9be66ee53fd) stayed eligible
because its name doesn't contain "SIMULATION". Verified via psql this
is fabricated seed data, not a real historical event:
  - all 6,145 revenue transactions land within a 23-SECOND window
    (21:31:03-21:31:26) — no real Sundance night compresses into that
  - its venue is literally named "Sundance 2025 Simulation"
  - its scheduled_at (2026-06-05) doesn't match what its own name
    claims (2025-06-15) — the name is a fabricated label pointing at a
    real historical date, not the actual date this row represents

Does NOT touch already-explicitly-set rows: a row previously flipped
back to true by a human (e.g. correcting a false positive) would be
silently re-flipped false by re-running the same broad backfill.
Scoped to only the new "Sim " pattern so aa3's backfill isn't re-run.
"""
from alembic import op
import sqlalchemy as sa


revision = "aa4"
down_revision = "aa3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE events SET is_training_eligible = false WHERE name ILIKE '%Sim %'")
    )


def downgrade() -> None:
    # Not reversible to prior per-row state (aa3's backfill result isn't
    # recorded) — intentionally a no-op. Re-running aa3's backfill query
    # by hand would restore its baseline if ever needed.
    pass
