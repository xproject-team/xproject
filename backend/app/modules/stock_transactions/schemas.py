"""Pydantic v2 schemas for the stock_transactions module.

Schema roles:
- Ingestion: SaleIngestRequest (cascade) + ManualAdjustmentRequest (single row)
- Response: StockTransactionResponse (ledger row shape)
- Reconciliation: ReconciliationReport + ReconciliationLine

Ingestion vs. response asymmetry is deliberate:
- Ingest payloads describe INTENT ("sell 1 Mojito at Cocktail Bar")
- Response rows describe OUTCOME (the 1 parent + N children actually written)
"""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.stock_transactions.models import PaymentType, TransactionSource


# ─── Ingestion payloads ───────────────────────────────────────────────────────

class SaleIngestRequest(BaseModel):
    """POST /stock-transactions/sale — a drink was sold; run the cascade.

    Semantics:
    - product_id must be a DRINK (service validates)
    - If the drink has a recipe, each recipe item produces a child
      transaction decrementing that ingredient's bar_stock
    - source_idempotency_key is REQUIRED if source=slesh_pos (service checks)

    qty is decimal to support fractional sales (half-pours etc.) but
    typical use is qty=1 for "one drink sold".
    """
    event_id: UUID
    bar_id: UUID
    product_id: UUID
    qty: Decimal = Field(default=Decimal("1"), gt=0)
    price_cents: int = Field(..., ge=0, description="Total revenue for this sale in cents")
    source: TransactionSource
    payment_type: "PaymentType | None" = Field(
        default=None,
        description="Payment instrument used. Required for slesh_pos source; optional otherwise.",
    )
    source_idempotency_key: str | None = Field(
        default=None,
        max_length=255,
        description="REQUIRED when source=slesh_pos. Used to deduplicate retries.",
    )
    note: str | None = Field(default=None, max_length=500)

    @field_validator("source_idempotency_key")
    @classmethod
    def _strip_key(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


class ManualAdjustmentRequest(BaseModel):
    """POST /stock-transactions/adjustment — a manual correction.

    Writes a SINGLE standalone ledger row (no cascade). Used for:
    - Bartender reports breakage or spillage (source=manual_bartender)
    - Manager records a taste-test / comp (source=manual_adjustment)
    - Reconciliation engine writes corrections (source=reconciliation_correction)

    note is required (human-readable reason for the non-automated change).
    """
    event_id: UUID
    bar_id: UUID
    product_id: UUID
    qty: Decimal = Field(..., gt=0)
    source: TransactionSource = Field(
        ...,
        description="Must NOT be slesh_pos — use /sale for POS input.",
    )
    note: str = Field(..., min_length=3, max_length=500)

    @field_validator("source")
    @classmethod
    def _not_slesh(cls, v: TransactionSource) -> TransactionSource:
        if v is TransactionSource.SLESH_POS:
            raise ValueError(
                "source=slesh_pos is not valid for /adjustment; use /sale instead"
            )
        return v

    @field_validator("note")
    @classmethod
    def _strip_note(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 3:
            raise ValueError("note must be at least 3 characters after trimming")
        return stripped


# ─── Response shape ───────────────────────────────────────────────────────────

class StockTransactionResponse(BaseModel):
    """One ledger row as returned from queries."""
    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: float},
    )

    id: UUID
    event_id: UUID
    bar_id: UUID
    product_id: UUID
    bar_stock_id: UUID | None
    qty: Decimal
    deficit_qty: Decimal
    price_cents: int | None
    source: TransactionSource
    source_idempotency_key: str | None
    parent_transaction_id: UUID | None
    note: str | None
    created_at: datetime


class SaleIngestResponse(BaseModel):
    """Response for POST /sale: the parent tx plus all child (ingredient) txs.

    idempotency_replay=true means this POST hit an existing idempotency key
    and no new rows were written — the existing rows are returned as-is.
    """
    parent: StockTransactionResponse
    children: list[StockTransactionResponse]
    idempotency_replay: bool = Field(
        default=False,
        description="True if this POST matched an existing idempotency key.",
    )


# ─── Reconciliation report ────────────────────────────────────────────────────

class ReconciliationLine(BaseModel):
    """One product's depletion reconciliation at one bar within an event.

    Math:
        expected_consumption = allocated_qty - current_qty - returned_qty
        actual_consumption   = SUM(stock_transactions.qty WHERE product + bar + event)
        anomaly_qty          = actual_consumption - expected_consumption

    Positive anomaly = more consumed than stock accounting says (shrinkage,
    free pours, theft, missed allocation).
    Negative anomaly = less consumed than stock accounting says (stock count
    error, un-rung sales, returns not recorded).
    """
    model_config = ConfigDict(json_encoders={Decimal: float})

    bar_id: UUID
    product_id: UUID
    bar_stock_id: UUID
    allocated_qty: Decimal
    current_qty: Decimal
    returned_qty: Decimal
    expected_consumption: Decimal
    actual_consumption: Decimal
    anomaly_qty: Decimal


class ReconciliationReport(BaseModel):
    """Per-event reconciliation report returned by
    GET /stock-transactions/reconciliation/by-event/{event_id}.
    """
    model_config = ConfigDict(json_encoders={Decimal: float})

    event_id: UUID
    generated_at: datetime
    total_revenue_cents: int = Field(..., ge=0)
    transaction_count: int = Field(..., ge=0)
    lines: list[ReconciliationLine]
    anomaly_count: int = Field(..., ge=0, description="Lines where anomaly_qty != 0")
