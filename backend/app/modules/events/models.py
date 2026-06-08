"""SQLAlchemy ORM models for the events module.

Contains:
  - Venue: a physical location (belongs to a tenant)
  - Event: an event held at a venue (belongs to a tenant and a venue)
"""
from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, SmallInteger, String, Time
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

    __table_args__ = (
        CheckConstraint(
            "food_revenue_share_pct IS NULL OR "
            "(food_revenue_share_pct >= 0 AND food_revenue_share_pct <= 100)",
            name="events_food_share_pct_range",
        ),
    )

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

    # ─── Slesh-aligned event fields (Phase B w1, June 2 2026) ────────────
    # Added to mirror Omar's official Slesh "Project Plan - Cashless"
    # template (docs/sundance-1-setup-plan.md). All nullable to keep
    # existing rows valid. UI surfaces these on the Create Event wizard
    # tabs Overview + Parametri.

    # Stripe legal entity (Italian: ragione sociale) — required for
    # Stripe payments on Sundance. Filled from Excel sheet 1.
    stripe_ragione_sociale: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )

    # Time of day staff are expected to arrive (separate from
    # scheduled_at which is the public event start). Time-only, no date —
    # date is implied by scheduled_at.
    staff_arrival_time: Mapped[Time | None] = mapped_column(
        Time(), nullable=True,
    )

    # Wristband planning JSON. Shape TBD with Omar; current Excel says
    # "1800 x 4 tipologie diverse (7200 in totale)". Likely shape:
    # {"early_bird": 1800, "general": 1800, "vip": 1800, "staff": 1800}
    wristband_qty_per_type: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )

    # Top-up denominations in CENTS (consistent with money convention).
    # User app: typically [500, 1000, 2000, 5000, 10000] (5/10/20/50/100€)
    # Staff app: typically [500] (€5 single)
    topup_denominations_user: Mapped[list | None] = mapped_column(
        JSONB, nullable=True,
    )
    topup_denominations_staff: Mapped[list | None] = mapped_column(
        JSONB, nullable=True,
    )

    # Refund policy. Sundance defaults from Excel sheet 2:
    #   min credit = €1 (100 cents), fee = €0.50 (50 cents)
    refund_min_credit_cents: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    refund_fee_cents: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )

    # Refund request window. Refunds outside this window are rejected.
    # Filled from Excel sheet 2 (dates were placeholder "xx/xx/2026" —
    # Omar needs to confirm).
    refund_window_open_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    refund_window_close_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Revenue model (XProject-native, not Slesh).
    # Omar share of FOOD gross revenue (integer percent 0-100). Food is a
    # partnership: the owner keeps this percent, the food company the rest.
    #   omar_food_revenue = food_gross * food_revenue_share_pct / 100
    # NULL = 100 (no split). One value per event. Added x1, June 2026.
    food_revenue_share_pct: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True,
    )
