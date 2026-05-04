"""add latitude and longitude to venues

Revision ID: o2_add_venue_geo
Revises: o1_add_event_weather
Create Date: 2026-05-04

Adds two nullable columns to venues for geographic coordinates:
  - latitude   numeric(9,6)   — WGS84 degrees, -90.0..90.0
  - longitude  numeric(9,6)   — WGS84 degrees, -180.0..180.0

NUMERIC(9,6) gives ~11cm precision (5 decimal places of arc-degrees),
which is far more than weather queries need but is the standard
PostgreSQL pattern for geo coordinates without bringing in PostGIS.

Both columns nullable so historical venues remain valid; the weather
sync skips events whose venue lacks coordinates with a clear log line.

Spec: docs/slesh-integration-roadmap.md (Phase B - Weather Integration).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o2_add_venue_geo"
down_revision: Union[str, None] = "o1_add_event_weather"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "venues",
        sa.Column(
            "latitude",
            sa.Numeric(9, 6),
            nullable=True,
            comment="WGS84 latitude in decimal degrees (-90 to 90).",
        ),
    )
    op.add_column(
        "venues",
        sa.Column(
            "longitude",
            sa.Numeric(9, 6),
            nullable=True,
            comment="WGS84 longitude in decimal degrees (-180 to 180).",
        ),
    )


def downgrade() -> None:
    op.drop_column("venues", "longitude")
    op.drop_column("venues", "latitude")
