"""SQLAlchemy ORM model for the bars module.

A Bar represents a point of sale (POS) within an event venue.
In Slesh terminology this is a 'negozio' — could be a cocktail bar,
a food truck, or any other sales station.
"""
from uuid import UUID
from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel


class Bar(TenantScopedModel):
    """A point of sale within an event. Tenant-scoped."""

    __tablename__ = "bars"

    # Link to the event this bar operates in
    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Display name (e.g. "Cocktail Bar", "Focacceria", "Malandrino")
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Slesh 'negozio' identifier — used to match transactions to this bar
    slesh_negozio_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
    )

    # Type of bar: drinks, food, mixed
    bar_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="drinks",
    )

    # Is this bar currently active for the event?
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
