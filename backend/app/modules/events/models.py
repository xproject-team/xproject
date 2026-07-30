"""SQLAlchemy ORM models for the events module.

Contains:
  - Venue: a physical location (belongs to a tenant)
  - Event: an event held at a venue (belongs to a tenant and a venue)
"""
from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, SmallInteger, String, Text, Time, UniqueConstraint, text
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
    # ML training-set contamination guard (Phase F follow-up). true unless
    # backfilled/set false for simulation/test/seed events — see alembic
    # migration aa3 and predictions/nowcast/retrain.py.
    is_training_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"),
    )
    # Day 4 customer-intelligence panel — manual heat adjustment for the
    # demand model's category breakdown. See alembic migration ae1 for
    # the full rationale (one hot event isn't enough to fit a weather
    # feature responsibly; this is a deliberate manual toggle, never an
    # automatic model input). Off by default.
    hot_night_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
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


class EventOrder(TenantScopedModel):
    """Per-Slesh-order financial extras and metadata.

    Populated by `order_ingester` alongside `stock_transactions`,
    one row per Slesh order. Captures order-level fields Slesh
    provides (VAT, deposits, fiscal totals, discounts) plus order
    type (cash-desk | express | experience), payment type, and
    aggregate line counts. Consumed by `RevenueBreakdownService`.

    UPSERTed on (tenant_id, slesh_order_id) so Slesh re-emits during
    refunds, payment updates, etc. are idempotent.
    """
    __tablename__ = "event_orders"

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "slesh_order_id",
            name="uq_event_orders_tenant_slesh_order",
        ),
        Index(
            "ix_event_orders_tenant_event_time",
            "tenant_id", "event_id", "created_at_slesh",
        ),
        Index(
            "ix_event_orders_event_type",
            "event_id", "order_type",
        ),
        Index("ix_event_orders_customer_email", "customer_email"),
        Index("ix_event_orders_payment_token", "payment_token"),
    )

    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Slesh identifiers
    slesh_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    slesh_shop_id:  Mapped[str | None] = mapped_column(String(64), nullable=True)
    bar_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True,
    )

    # cash-desk | express | experience  (Slesh _type)
    order_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # Financial fields — cents only (no float drift)
    subtotal_cents:      Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    vat_cents:           Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    deposit_cents:       Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fiscal_gross_cents:  Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fiscal_net_cents:    Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    discount_cents:      Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pre_promo_cents:     Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Per-order summary
    payment_type:         Mapped[str | None] = mapped_column(String(32), nullable=True)
    cart_line_count:      Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    confirmed_line_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    refunded_line_count:  Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Safety net — full Slesh __* dict for fields we do not model yet
    raw_extras: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Customer identity — lifted out of raw_extras into queryable columns.
    # customer_email is normalized (lowercase + trimmed) at write time in
    # order_ingester.py, never here. payment_token is the physical
    # wristband/card credential; compare it against raw_extras.user._id
    # to learn whether a band maps 1:1 to a person or is a shared wallet.
    customer_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_token:  Mapped[str | None] = mapped_column(Text, nullable=True)

    # When Slesh recorded the order
    created_at_slesh: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    # When we wrote this row
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("now()"),
    )

