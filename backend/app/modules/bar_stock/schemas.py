"""Pydantic v2 schemas for the bar_stock module.

One response schema + four action payloads:

    Response           — what API returns
    AllocateRequest    — POST /bar-stock/allocate         (create or topup)
    ConsumeRequest     — POST /bar-stock/{id}/consume     (decrement current_qty)
    ReturnRequest      — POST /bar-stock/{id}/return      (increment returned_qty)
    AdjustRequest      — POST /bar-stock/{id}/adjust      (corrections)

We deliberately DO NOT expose a generic PATCH for quantities — all
quantity changes go through one of the four semantic actions, which
makes the downstream audit log (Step 6) cleanly mappable.
"""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ─── Response ─────────────────────────────────────────────────────────────────

class BarStockResponse(BaseModel):
    """Shape returned by all bar_stock endpoints."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    bar_id: UUID
    product_id: UUID
    allocated_qty: int = Field(..., ge=0)
    current_qty: int = Field(..., ge=0)
    returned_qty: int = Field(..., ge=0)


# ─── Action payloads ──────────────────────────────────────────────────────────

class AllocateRequest(BaseModel):
    """POST /bar-stock/allocate — transfer stock IN from warehouse to a bar.

    Two behaviors based on whether a bar_stock row already exists for
    (event, bar, product):
    - Not exists: create new row. allocated_qty = current_qty = qty.
    - Exists:     top up. allocated_qty += qty AND current_qty += qty.

    Service validates event exists, bar belongs to event, product exists
    and isn't archived.
    """
    event_id: UUID
    bar_id: UUID
    product_id: UUID
    qty: int = Field(..., gt=0, description="Quantity to allocate. Must be positive.")


class ConsumeRequest(BaseModel):
    """POST /bar-stock/{id}/consume — decrement current_qty.

    Used by bartender flows + Slesh POS scan ingestion (Step 6).
    Service enforces: new_current = current_qty - qty >= 0.
    """
    qty: int = Field(..., gt=0, description="Quantity consumed. Must be positive.")


class ReturnRequest(BaseModel):
    """POST /bar-stock/{id}/return — transfer stock OUT to warehouse.

    Called at event end for unused stock. Service enforces:
    - new_returned = returned_qty + qty
    - new_returned <= allocated_qty
    - effective stock left at bar = current_qty (unchanged by return,
      because 'returned' is a separate tally for reconciliation)

    NOTE: return does NOT decrement current_qty. The returned quantity
    is a SEPARATE counter that reconciliation uses. Physically-speaking,
    by the time stock is 'returned', bartenders have stopped pouring
    so current_qty is frozen. If that assumption changes, this contract
    needs revisiting.
    """
    qty: int = Field(..., gt=0, description="Quantity returned to warehouse. Must be positive.")


class AdjustRequest(BaseModel):
    """POST /bar-stock/{id}/adjust — correction / manual override.

    Rare operation, used for physical recount corrections (e.g. manager
    recounts at end of event and finds 2 missing bottles).

    Any combination of new_allocated, new_current, new_returned may be
    provided. Service enforces all invariants after applying:
    - new_current    <= new_allocated
    - new_returned   <= new_allocated
    - all >= 0

    Omitted fields keep their existing value.
    """
    new_allocated_qty: int | None = Field(default=None, ge=0)
    new_current_qty: int | None = Field(default=None, ge=0)
    new_returned_qty: int | None = Field(default=None, ge=0)
    reason: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Audit note explaining why this manual adjustment was needed.",
    )


class BulkAllocateItem(BaseModel):
    """One row of a bulk allocation — (bar, product, qty)."""

    bar_id: UUID
    product_id: UUID
    qty: int = Field(
        ...,
        ge=0,
        description=(
            "mode='set':   target allocated_qty for this (bar, product). "
            "mode='topup': quantity to add (must be > 0)."
        ),
    )


class BulkAllocateRequest(BaseModel):
    """POST /bar-stock/bulk-allocate — allocate many rows in one transaction.

    Semantics by mode:
    - 'set' (default): each item's qty is the TARGET allocated_qty.
        delta = qty - existing.allocated_qty
        allocated_qty = qty;  current_qty += delta (never below 0).
        Re-posting the same payload is a no-op → idempotent. This is
        the mode the Inventory Allocation page and CSV paste-in use.
    - 'topup': identical semantics to single POST /bar-stock/allocate
        (allocated_qty += qty, current_qty += qty), applied per item.

    All-or-nothing: every item is validated before anything is applied;
    one commit at the end. Any invalid item rejects the whole batch with
    a per-item error report.
    """

    event_id: UUID
    mode: Literal["set", "topup"] = "set"
    items: list[BulkAllocateItem] = Field(..., min_length=1, max_length=500)


class BulkAllocateItemError(BaseModel):
    """Validation failure for one item, reported by payload index."""

    index: int
    bar_id: UUID
    product_id: UUID
    error: str


class BulkAllocateResponse(BaseModel):
    """Result of a successful bulk allocation."""

    event_id: UUID
    mode: str
    created: int
    updated: int
    unchanged: int
    rows: list[BarStockResponse]
