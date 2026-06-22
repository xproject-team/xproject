"""SQLAlchemy ORM models for the recharge module.

Models:
  RechargeStation       Stand-alone desk for the event. One per event
                        by default, named 'Recharge Desk'.
  RechargeDevice        POS device at a station (Ss-ricarica-N).
  RicaricaTransaction   Money loaded onto wristbands. Stores individual
                        transactions when available (source='api'), or
                        per-device-per-payment-method aggregates from
                        Slesh Excel exports (source='slesh_export').
                        transaction_count distinguishes a live tx (1)
                        from an aggregate row (N).
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Integer, String, text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel


class RechargeStation(TenantScopedModel):
    """Stand-alone wristband-recharge desk at an event."""

    __tablename__ = "recharge_stations"

    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        server_default=text("'Recharge Desk'"),
    )


class RechargeDevice(TenantScopedModel):
    """POS device at a recharge station (Ss-ricarica-N@slesh.it)."""

    __tablename__ = "recharge_devices"

    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recharge_station_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("recharge_stations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    slesh_operator_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )
    slesh_operator_email: Mapped[str] = mapped_column(
        String(255), nullable=False,
    )
    device_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'cashier'"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    last_order_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class RicaricaTransaction(TenantScopedModel):
    """A wristband top-up transaction or aggregate row."""

    __tablename__ = "ricarica_transactions"

    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recharge_device_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("recharge_devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # 1 for live API rows; N for Excel aggregates.
    transaction_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1"),
    )

    # 'stripe_ttp' | 'contanti' | 'crediti' | etc.
    payment_method: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )

    # Populated when ingested from live Slesh API, NULL for Excel aggregates.
    slesh_transaction_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
    )
    created_at_slesh: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("now()"),
    )

    # 'slesh_export' | 'api' | 'manual'
    source: Mapped[str] = mapped_column(String(32), nullable=False)
