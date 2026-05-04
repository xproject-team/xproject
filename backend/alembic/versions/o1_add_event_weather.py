"""add weather snapshot to events

Revision ID: o1_add_event_weather
Revises: n1_add_payment_type
Create Date: 2026-05-04

Adds two nullable columns to events for storing Open-Meteo forecasts:

  - weather_snapshot   JSONB   — full response (current + hourly arrays).
  - weather_fetched_at TIMESTAMPTZ — when we last hit Open-Meteo.

Why JSONB instead of a normalised weather_hourly table:
  - Open-Meteo returns 5+ hourly metrics x 48+ hours per event = 240+ rows
    per event if normalised. We always consume the snapshot as a unit
    (dashboard pill + post-event report), so normalisation buys us no
    query flexibility but adds cost.
  - JSONB keeps the original API response intact for future ML features
    we have not yet designed (explainability, cross-validation against
    other providers).
  - GIN index on the column is available later if filtering ever matters;
    for v1 we always look up by event_id (already indexed), then read
    the JSONB blob whole.

Both columns are NULLABLE so historical events without weather data
remain valid; the sync script populates them on demand.

Spec: docs/slesh-integration-roadmap.md (Phase B - Weather Integration).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "o1_add_event_weather"
down_revision: Union[str, None] = "n1_add_payment_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "weather_snapshot",
            JSONB(),
            nullable=True,
            comment=(
                "Full Open-Meteo forecast snapshot (current + hourly arrays). "
                "NULL for historical events; populated by the weather sync."
            ),
        ),
    )
    op.add_column(
        "events",
        sa.Column(
            "weather_fetched_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of the most recent Open-Meteo fetch for this event.",
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "weather_fetched_at")
    op.drop_column("events", "weather_snapshot")
