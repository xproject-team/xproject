"""events.hot_night_override — manual heat adjustment toggle for the demand model

Revision ID: ae1
Revises: ad1
Create Date: 2026-07-30

Day 4 customer-intelligence panel. The demand model's category-share
breakdown under-predicts spritz / over-predicts cocktail on hot nights
(Jul-19, the only >=33C event so far, saw spritz at 27-36% actual vs
~15-18% pooled expectation during hours 1-5 — see Day 3's closeout
report). One hot event isn't enough to fit a weather feature
responsibly, so this stays a manual, explicit, per-event toggle rather
than an automatic model input: a manager flips it on when tonight is
genuinely hot, the API applies a fixed +12-19pp spritz-share boost for
hours 1-5 (renormalizing the other categories down), and the frontend
labels the adjusted numbers as indicative. Off by default; never
inferred from a forecast automatically.

Column shape:
  - hot_night_override BOOLEAN NOT NULL DEFAULT false

Backward compatibility: existing rows all default to false (no
adjustment) — behavior is unchanged unless someone explicitly flips it.
"""
from alembic import op
import sqlalchemy as sa


revision = "ae1"
down_revision = "ad1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "hot_night_override", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "hot_night_override")
