"""SQLAlchemy ORM models for the customer-analytics feature layer.

CustomerSession: one row per (event, customer_key) — the aggregate profile
a model would train on.
CustomerPurchase: one row per drink/food line attributed to a customer —
the detail table CustomerSession is built from.

Built exclusively from event_orders, stock_transactions, products, and
bars — the Slesh-sourced tables. Never joins recipes, bar_stock,
inventory, alerts, or warehouse; those are out of scope for this layer
by design (see app/scripts/build_customer_features.py).

customer_key is event_orders.raw_extras->'user'->>'_id' — the Mongo
account id, the only per-customer handle we have. Orders without one
(cash/unidentified) never appear in either table; nothing here invents
an identity.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel


class CustomerSession(TenantScopedModel):
    """One customer's aggregate activity at one event.

    "Session" here means the span between a customer's first and last
    purchase at the event — NOT true physical attendance duration. A
    customer who buys once at 14:00 and again at 20:00 has a 6-hour
    session_minutes even if they left and came back, or never left at
    all. Do not read this as time-on-site.
    """
    __tablename__ = "customer_sessions"

    __table_args__ = (
        UniqueConstraint("event_id", "customer_key", name="uq_customer_sessions_event_customer"),
    )

    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False,
    )
    customer_key: Mapped[str] = mapped_column(String(64), nullable=False)

    first_order_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_order_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # last_order_at - first_order_at, in minutes. Time-BETWEEN-purchases,
    # not attendance duration — see class docstring.
    session_minutes: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    order_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_spend_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    avg_order_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)

    distinct_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    first_bar_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("bars.id", ondelete="SET NULL"), nullable=True,
    )

    # customer_email's domain != 'slesh.it'. NULL when none of this
    # customer's orders at this event carry a customer_email at all
    # (Slesh omitted it, or every order was skipped by the identity
    # backfill's drift gate) — "unknown", not "guest".
    is_registered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Domain only — the full address is never stored in this table.
    email_domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'live' (captured by the poller at ingestion time) or 'backfill'
    # (recovered after the fact — Sundance 14 provenance). Read from
    # event_orders.raw_extras->>'user_source', defaulting to 'live' when
    # absent (true for every order that predates the backfill script).
    user_source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="live")

    drink_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    food_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Drink-only breakdown; these six sum to drink_count. Food lines are
    # not categorized here — see food_count above.
    beer_count:     Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cocktail_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    spritz_count:   Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    wine_count:     Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    premium_count:  Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    other_count:    Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class CustomerPurchase(TenantScopedModel):
    """One drink or food line attributed to a customer.

    Joined from stock_transactions via source_idempotency_key (format
    "slesh:{order_id}:{line_id}") back to event_orders.slesh_order_id —
    see build_customer_features.py for the exact join. ordered_at is
    ALWAYS event_orders.created_at_slesh, never
    stock_transactions.created_at (the latter is ingestion time, not
    purchase time — see the identity audit's time-basis findings).
    """
    __tablename__ = "customer_purchases"

    __table_args__ = (
        Index("ix_customer_purchases_event_customer", "event_id", "customer_key"),
        Index("ix_customer_purchases_event_ordered_at", "event_id", "ordered_at"),
        Index("ix_customer_purchases_event_category", "event_id", "category"),
    )

    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False,
    )
    customer_key: Mapped[str] = mapped_column(String(64), nullable=False)

    slesh_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False,
    )
    # Denormalized snapshot of the product name at build time — the
    # catalog has known duplicate entries (case/whitespace variants);
    # this is what was actually on the line, not a live join.
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    # One of: beer | cocktail | spritz | wine | premium | other | food.
    # The first six are the drink-category bucket (see
    # build_customer_features.py::bucket_category); 'food' is every
    # product_type=FOOD line, uncategorized by design.
    category: Mapped[str] = mapped_column(String(16), nullable=False)

    bar_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("bars.id", ondelete="SET NULL"), nullable=True,
    )
    qty: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
