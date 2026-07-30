"""model_artifacts.file_bytes — durable storage for the pickled bundle

Revision ID: af1
Revises: ae1
Create Date: 2026-07-30

ROOT CAUSE this fixes: retrain.py wrote each artifact's pickle to local
container disk (file_path). Railway's app-service container has no
attached volume — confirmed via `railway volume list` (only Postgres
and Redis have one) — so that disk is wiped on every deploy/restart.
The demand_forecast v3 artifact's DB row survived (Postgres persists),
is_active=true, every loader.py predicate matched, but the file itself
was gone by the next deploy: loader.py's broad except swallowed the
resulting FileNotFoundError and reported "model not yet trained",
which is a materially different, misleading state (see retrain.py /
loader.py changes alongside this migration for the messaging fix).

file_bytes stores the exact bytes pickle.dumps(bundle) produced —
small (~3.6KB observed for demand_forecast) — directly in Postgres,
which already has a durable volume. file_path is KEPT for backward
compatibility and local debugging (retrain.py still writes it,
best-effort) but nothing depends on it anymore: loader.py prefers
file_bytes and only falls back to file_path if file_bytes is NULL
(e.g. rows written before this migration — those will correctly report
"model artifact unavailable" once their on-disk file is inevitably
gone, rather than silently pretending to work).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "af1"
down_revision = "ae1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_artifacts",
        sa.Column("file_bytes", postgresql.BYTEA(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_artifacts", "file_bytes")
