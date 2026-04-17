"""add stock_transactions table (append-only ledger)

Revision ID: f1_add_stock_transactions
Revises: e1_add_recipes
Create Date: 2026-04-17

Creates the stock_transactions table and transaction_source enum.

stock_transactions is an APPEND-ONLY LEDGER:
- Every row represents a single stock-changing event (sale, manual
  adjustment, reconciliation correction).
- Rows are NEVER updated or deleted. Corrections are new rows.
- This enables a complete, auditable history for reconciliation.

Parent-child structure (Q4 cascade):
- A sale of 1 Mojito writes 1 PARENT row (product_id=Mojito) + N
  CHILD rows (product_id=each ingredient, parent_transaction_id=parent.id)
- Children carry the parent_transaction_id FK (self-reference, SET NULL
  on parent delete — deletions don't happen in normal flow but the
  CHECK makes re-ingesting via downgrade+upgrade safer).
- parent_transaction_id is NULL for standalone transactions
  (manual adjustments, reconciliation corrections).

Idempotency (Q3):
- source_idempotency_key is REQUIRED (NOT NULL) when source='slesh_pos'
  and nullable otherwise. Service enforces the NOT-NULL-for-slesh rule.
- UNIQUE index on (tenant_id, source, source_idempotency_key) WHERE
  source_idempotency_key IS NOT NULL prevents Slesh retries from
  double-counting; service returns existing row on conflict.

Numeric types:
- qty: NUMERIC(12,3) — supports fractional decrements from recipe
  cascades (e.g. 0.05 bottles). bar_stock.current_qty remains INTEGER
  per Q5; the service layer rounds qty to integer when applying to
  bar_stock (see service for rounding policy).
- price_cents: INTEGER nullable (only parent txs carry revenue).

Deficit tracking (Q6):
- deficit_qty NUMERIC(12,3) NOT NULL DEFAULT 0 — the quantity we
  COULDN'T deduct because bar_stock was already at 0. Reconciliation
  surfaces non-zero deficits as anomalies.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f1_add_stock_transactions"
down_revision: str | None = "e1_add_recipes"
branch_labels: str | None = None
depends_on: str | None = None


TRANSACTION_SOURCE_VALUES = (
    "slesh_pos",
    "manual_bartender",
    "manual_adjustment",
    "reconciliation_correction",
)


def upgrade() -> None:
    # ─── Create enum ──────────────────────────────────────────────────────────
    transaction_source_enum = postgresql.ENUM(
        *TRANSACTION_SOURCE_VALUES,
        name="transaction_source",
        create_type=False,
    )
    transaction_source_enum.create(op.get_bind(), checkfirst=True)

    # ─── Create table ─────────────────────────────────────────────────────────
    op.create_table(
        "stock_transactions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
        # ─── Location in the event lifecycle ─────────────────────────────────
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "bar_stock_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bar_stock.id", ondelete="SET NULL"),
            nullable=True,
            comment=(
                "The bar_stock row this transaction decremented. NULL if no "
                "stock row existed (e.g. selling an unallocated ingredient)."
            ),
        ),
        # ─── Quantity + revenue ──────────────────────────────────────────────
        sa.Column(
            "qty",
            sa.Numeric(12, 3),
            nullable=False,
            comment="Positive quantity consumed (decrement applied to bar_stock).",
        ),
        sa.Column(
            "deficit_qty",
            sa.Numeric(12, 3),
            nullable=False,
            server_default=sa.text("0"),
            comment=(
                "Portion of qty that couldn't be deducted because bar_stock "
                "was already at 0. Non-zero = anomaly for reconciliation."
            ),
        ),
        sa.Column(
            "price_cents",
            sa.Integer,
            nullable=True,
            comment="Revenue cents. NULL on child (ingredient) txs.",
        ),
        # ─── Lineage ─────────────────────────────────────────────────────────
        sa.Column(
            "source",
            postgresql.ENUM(
                *TRANSACTION_SOURCE_VALUES,
                name="transaction_source",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "source_idempotency_key",
            sa.String(length=255),
            nullable=True,
            comment=(
                "Required when source='slesh_pos'. Used to deduplicate POS "
                "retries. Service enforces the NOT-NULL-for-slesh rule."
            ),
        ),
        sa.Column(
            "parent_transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stock_transactions.id", ondelete="SET NULL"),
            nullable=True,
            comment="Non-null on child (ingredient) txs spawned by cascade.",
        ),
        sa.Column(
            "note",
            sa.Text,
            nullable=True,
            comment="Optional human-readable note (required for manual_adjustment).",
        ),
        # ─── Constraints ─────────────────────────────────────────────────────
        sa.CheckConstraint(
            "qty > 0",
            name="stock_transactions_qty_positive",
        ),
        sa.CheckConstraint(
            "deficit_qty >= 0",
            name="stock_transactions_deficit_nonneg",
        ),
        sa.CheckConstraint(
            "deficit_qty <= qty",
            name="stock_transactions_deficit_lte_qty",
        ),
        sa.CheckConstraint(
            "price_cents IS NULL OR price_cents >= 0",
            name="stock_transactions_price_nonneg",
        ),
    )

    # ─── Indexes ──────────────────────────────────────────────────────────────
    op.create_index(
        "ix_stock_transactions_event_id",
        "stock_transactions",
        ["event_id"],
    )
    op.create_index(
        "ix_stock_transactions_bar_id",
        "stock_transactions",
        ["bar_id"],
    )
    op.create_index(
        "ix_stock_transactions_product_id",
        "stock_transactions",
        ["product_id"],
    )
    op.create_index(
        "ix_stock_transactions_bar_stock_id",
        "stock_transactions",
        ["bar_stock_id"],
    )
    op.create_index(
        "ix_stock_transactions_parent_transaction_id",
        "stock_transactions",
        ["parent_transaction_id"],
    )
    op.create_index(
        "ix_stock_transactions_created_at",
        "stock_transactions",
        ["created_at"],
    )
    op.create_index(
        "ix_stock_transactions_event_bar_created",
        "stock_transactions",
        ["event_id", "bar_id", "created_at"],
    )

    # ─── Unique idempotency index (partial — only when key is set) ───────────
    op.create_index(
        "uq_stock_transactions_idempotency",
        "stock_transactions",
        ["tenant_id", "source", "source_idempotency_key"],
        unique=True,
        postgresql_where=sa.text("source_idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_stock_transactions_idempotency", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_event_bar_created", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_created_at", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_parent_transaction_id", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_bar_stock_id", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_product_id", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_bar_id", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_event_id", table_name="stock_transactions")
    op.drop_table("stock_transactions")

    postgresql.ENUM(name="transaction_source").drop(op.get_bind(), checkfirst=True)
