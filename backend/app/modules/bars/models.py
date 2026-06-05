"""SQLAlchemy ORM model for the bars module.

A Bar represents a point of sale (POS) within an event venue.
In Slesh terminology this is a 'negozio' — could be a cocktail bar,
a food truck, or any other sales station.
"""
from uuid import UUID
from sqlalchemy import Boolean, ForeignKey, Integer, String
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

    # ─── Slesh-aligned fields (Phase B w2, June 2 2026) ──────────────
    # Mirrors Omar's "Project Plan - Cashless" Excel sheets 3 (Device
    # Count) and 4 (Listini Bar). Both nullable — bars can exist
    # before device assignment / Slesh categorization.

    # POS device count assigned to this bar. From Excel sheet 3:
    # MAIN BAR=9, NO.3 BAR=1, STAGE BAR=4, Malandrino=2, etc.
    device_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )

    # Slesh-side category label. Distinct from bar_type (which is
    # XProject-native: food/drinks/merch). Slesh uses labels like
    # "Panineria" (sandwich shop), "Bar", "Bar + Cassa". We snapshot
    # the Slesh-side label here for Slesh-fidelity reporting.
    slesh_category: Mapped[str | None] = mapped_column(
        String(40), nullable=True,
    )
