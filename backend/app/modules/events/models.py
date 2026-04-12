"""SQLAlchemy ORM models for the events module.

Contains:
  - Venue: a physical location (belongs to a tenant)
  - Event: an event held at a venue (belongs to a tenant and a venue)
"""
from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel


class EventStatus(str, PyEnum):
    """Lifecycle of an event."""
    DRAFT = "draft"           # Being planned, not started
    ACTIVE = "active"         # Scheduled, pre-event preparation
    LIVE = "live"             # Happening right now
    COMPLETED = "completed"   # Finished
    CANCELLED = "cancelled"   # Called off


class Venue(TenantScopedModel):
    """A physical location where events happen.

    Examples: 'Sundance Venue', 'Latteria Garbatella', 'EUR Spa'.
    """
    __tablename__ = "venues"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
