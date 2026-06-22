"""SQLAlchemy ORM model for bar_devices.

A BarDevice is a POS device (= Slesh operator account) assigned to a
bar for a specific event. Devices are event-scoped: re-assigning a
bartender to a different bar creates a new row for the next event.

In Slesh terminology this maps to an 'operator': each Slesh operator
has a Mongo ObjectID (slesh_operator_id) and an email like
'Ss-bar-main-1@slesh.it' that encodes the bar prefix and device number.

Excel-imported devices set slesh_operator_id to the email until the
live ingester resolves it to the real Mongo ObjectID.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel


class BarDevice(TenantScopedModel):
    """POS device assigned to a bar for one event."""

    __tablename__ = "bar_devices"

    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bar_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("bars.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Slesh's Mongo ObjectID — stable join key with order data.
    # For Excel-imported devices, falls back to the email.
    slesh_operator_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )
    slesh_operator_email: Mapped[str] = mapped_column(
        String(255), nullable=False,
    )

    # Device number within the bar (1..N). Parsed from the email.
    device_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )

    # 'bartender' or 'helper'. Used to roll up staff_count.
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'bartender'"),
    )

    display_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )

    # Flipped to true once the device processes its first order.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )

    # Last observed activity, populated by the order ingester.
    last_order_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
