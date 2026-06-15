"""SQLAlchemy ORM model for stock_transactions.

Key design points:
- Self-referential parent_transaction_id: a cascade sale produces a
  parent row plus N children pointing back to it via parent_transaction_id.
- bar_stock_id is SET NULL on stock deletion so we preserve historical
  transactions even if the bar_stock row is later cleaned up.
- Native Postgres ENUM for source via product_unit pattern (create_type=False).
"""
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel


# ─── Enum (matches transaction_source Postgres type) ─────────────────────────

class TransactionSource(str, PyEnum):
    """Provenance of a stock_transaction row. Drives reconciliation rules
    and the UI's transaction-history timeline icons.
    """
    SLESH_POS = "slesh_pos"
    MANUAL_BARTENDER = "manual_bartender"
    MANUAL_ADJUSTMENT = "manual_adjustment"
    RECONCILIATION_CORRECTION = "reconciliation_correction"


class PaymentType(str, PyEnum):
    """Payment instrument used for a transaction.

    Values mirror Slesh's payment.type vocabulary. The single rename:
    Slesh's 'tap-to-pay' becomes 'tap_to_pay' (Postgres ENUMs don't
    support hyphens). Mapping happens in order_ingester.py.

    NULL on the column = unknown (manual adjustments, or rows ingested
    before B8b migration). Backfill script populates historical rows.
    """
    STRIPE     = "stripe"
    ADYEN      = "adyen"
    TOKEN      = "token"          # NFC wristband
    CASH       = "cash"
    CARD       = "card"
    TAP_TO_PAY = "tap_to_pay"
    MIXED      = "mixed"


# ─── Model ────────────────────────────────────────────────────────────────────

class StockTransaction(TenantScopedModel):
    """One row = one stock-changing event. Append-only."""
    __tablename__ = "stock_transactions"

    __table_args__ = (
        CheckConstraint("qty > 0", name="stock_transactions_qty_positive"),
        CheckConstraint(
            "deficit_qty >= 0",
            name="stock_transactions_deficit_nonneg",
        ),
        CheckConstraint(
            "deficit_qty <= qty",
            name="stock_transactions_deficit_lte_qty",
        ),
        CheckConstraint(
            "price_cents IS NULL OR price_cents >= 0",
            name="stock_transactions_price_nonneg",
        ),
        # Partial unique idempotency index: prevents Slesh POS retries from
        # double-counting, but allows NULL keys (manual adjustments etc.)
        Index(
            "uq_stock_transactions_idempotency",
            "tenant_id", "source", "source_idempotency_key",
            unique=True,
            postgresql_where=text("source_idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_stock_transactions_event_bar_created",
            "event_id", "bar_id", "created_at",
        ),
    )

    # ─── Location in the event ───────────────────────────────────────────────
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
    bar_stock_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("bar_stock.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ─── Quantities ──────────────────────────────────────────────────────────
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    deficit_qty: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
        nullable=False,
        server_default=text("0"),
    )
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ─── Lineage ─────────────────────────────────────────────────────────────
    source: Mapped[TransactionSource] = mapped_column(
        PgEnum(
            TransactionSource,
            name="transaction_source",
            values_callable=lambda enum: [e.value for e in enum],
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )
    source_idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    parent_transaction_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("stock_transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ─── Payment instrument (added in B8b for wristband activity feed) ───
    payment_type: Mapped["PaymentType | None"] = mapped_column(
        PgEnum(
            PaymentType,
            name="transaction_payment_type",
            values_callable=lambda enum: [e.value for e in enum],
            native_enum=True,
            create_type=False,    # migration n1_add_payment_type creates it
        ),
        nullable=True,
        index=True,
    )

    # ─── POS line status (mirrors Slesh CartLine.status) ─────────────────
    # 'confirmed' for normal sales, 'refunded' for cup/bottle returns.
    # Aggregation queries filter on status='confirmed' so refunds don't
    # inflate revenue. Default keeps legacy/manual rows behaving as before.
    pos_line_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'confirmed'"),
        index=True,
    )
