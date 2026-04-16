"""SQLAlchemy ORM model for the event_products module.

An EventProduct represents a menu item on a specific bar at a specific
event, with event-level price and optional tier_rank override.

Design notes (locked in Step 3 Q1-Q3):
- bar_id is REQUIRED (no event-wide menu items — always attached to a bar)
- price_cents is REQUIRED (Omar sets every price explicitly per event)
- tier_rank_override is nullable (falls back to Product.tier_rank when null)
- is_available flag lets Owner temporarily disable items without deleting
  (preserves historical menu structure + transaction references)
"""
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel


class EventProduct(TenantScopedModel):
    """A single menu line item: Product X at Bar Y within Event Z."""
    __tablename__ = "event_products"

    __table_args__ = (
        CheckConstraint(
            "price_cents >= 0",
            name="event_products_price_nonneg",
        ),
        CheckConstraint(
            "tier_rank_override IS NULL OR "
            "(tier_rank_override >= 1 AND tier_rank_override <= 4)",
            name="event_products_tier_rank_range",
        ),
        Index(
            "uq_event_products_event_bar_product",
            "event_id", "bar_id", "product_id",
            unique=True,
        ),
    )

    # ─── Relationships ────────────────────────────────────────────────────────
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
    product_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # ─── Event-specific overrides ─────────────────────────────────────────────
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    tier_rank_override: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True,
    )

    is_available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        index=True,
    )
