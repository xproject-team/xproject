"""SQLAlchemy ORM model for the Venue entity.

Multi-tenant: every venue belongs to exactly one tenant. A venue can host
multiple events over time (1:N relationship from Venue to Event).

Contract reference: §5 (multi-tenant isolation).
"""
from sqlalchemy import Integer, String, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from decimal import Decimal

from app.core.tenancy import TenantScopedModel


class Venue(TenantScopedModel):
    """A physical location where events happen.

    Examples: 'Sundance Venue', 'Villa Roma', 'Latteria Garbatella'.
    """
    __tablename__ = "venues"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ─── Geographic coordinates (added Phase B - weather integration) ───
    # WGS84 decimal degrees. NULL until populated; weather sync skips
    # events whose venue lacks coordinates with a clear log line.
    latitude:  Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6), nullable=True,
    )
    longitude: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6), nullable=True,
    )
