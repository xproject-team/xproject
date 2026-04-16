"""SQLAlchemy ORM model for bar_stock.

Invariants enforced at the DB level (CHECK constraints in migration d1):
- allocated_qty >= 0
- current_qty   >= 0
- returned_qty  >= 0
- current_qty   <= allocated_qty
- returned_qty  <= allocated_qty

The service layer enforces additional cross-quantity rules:
- consume: new_current = current - delta, must remain >= 0
- return:  new_returned = returned + delta, must remain <= allocated
- adjust (allocated): new_allocated must remain >= current AND >= returned
"""
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel


class BarStock(TenantScopedModel):
    """One inventory row for (event, bar, product) — tracks full lifecycle."""
    __tablename__ = "bar_stock"

    __table_args__ = (
        CheckConstraint("allocated_qty >= 0", name="bar_stock_allocated_nonneg"),
        CheckConstraint("current_qty >= 0", name="bar_stock_current_nonneg"),
        CheckConstraint("returned_qty >= 0", name="bar_stock_returned_nonneg"),
        CheckConstraint(
            "current_qty <= allocated_qty",
            name="bar_stock_current_lte_allocated",
        ),
        CheckConstraint(
            "returned_qty <= allocated_qty",
            name="bar_stock_returned_lte_allocated",
        ),
        Index(
            "uq_bar_stock_event_bar_product",
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

    # ─── Quantity columns ────────────────────────────────────────────────────
    allocated_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    current_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    returned_qty: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
