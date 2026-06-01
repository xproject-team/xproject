"""SQLAlchemy ORM models for the events module.

Contains:
  - Venue: a physical location (belongs to a tenant)
  - Event: an event held at a venue (belongs to a tenant and a venue)
"""
from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel


class EventStatus(str, PyEnum):
    """Lifecycle of an event."""
    DRAFT = "draft"           # Being planned, not started
    ACTIVE = "active"         # Scheduled, pre-event preparation
    LIVE = "live"             # Happening right now
    COMPLETED = "completed"   # Finished
    CANCELLED = "cancelled"   # Called off




class Event(TenantScopedModel):
    """A scheduled event hosted at a venue."""
    __tablename__ = "events"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    venue_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("venues.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, name="event_status", native_enum=True),
        nullable=False,
        default=EventStatus.DRAFT,
    )
    expected_guest_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    # Replaced `scheduled_date: date` with two DateTimes (2026-06-01,
    # commit u1 migration). Owner now picks exact start + end time at
    # event creation. Used by:
    #   - auto-go-live cron (promotes draft -> live at scheduled_at)
    #   - auto-end cron (live -> completed if past scheduled_end_at
    #     AND no Slesh tx in last 60min)
    #   - manual go-live window: [scheduled_at - 1h, scheduled_at]
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    scheduled_end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # ─── Weather snapshot (added Phase B — weather integration) ──────────
    # Full Open-Meteo response (current + hourly arrays). NULL for events
    # whose weather has not yet been synced. JSONB rather than normalised
    # rows because the snapshot is always read whole and we want to keep
    # the raw API response for future ML / explainability work.
    weather_snapshot: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )
    weather_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
