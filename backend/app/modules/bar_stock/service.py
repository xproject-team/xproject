"""Business logic for the bar_stock module.

Four semantic actions:
    allocate  — transfer stock IN from warehouse (create-or-topup)
    consume   — bartender pour or Slesh scan  (decrement current_qty)
    return    — transfer stock OUT back to warehouse at event end
    adjust    — manual correction (audited with required reason)

Cross-module validation on allocate:
- event exists in tenant
- bar exists in tenant AND belongs to that event
- product exists in tenant AND is NOT archived

Quantity invariants (some also enforced as DB CHECKs — service layer
catches them with friendly errors before the DB does):
- allocated_qty >= 0
- current_qty >= 0
- returned_qty >= 0
- current_qty <= allocated_qty
- returned_qty <= allocated_qty
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bar_stock.models import BarStock
from app.modules.bar_stock.repository import BarStockRepository
from app.modules.bar_stock.realtime_publish import publish_stock_change
from app.modules.bar_stock.schemas import (
    AdjustRequest,
    AllocateRequest,
    ConsumeRequest,
    ReturnRequest,
)
from app.modules.bars.repository import BarRepository
from app.modules.events.repository import EventRepository
from app.modules.products.repository import ProductRepository


# ─── Domain exceptions ────────────────────────────────────────────────────────

class BarStockNotFoundError(Exception):
    """Stock row does not exist or tenant mismatch. -> 404."""


class EventNotFoundError(Exception):
    """Event in allocate request doesn't exist. -> 404."""


class BarNotFoundError(Exception):
    """Bar in allocate request doesn't exist. -> 404."""


class BarNotInEventError(Exception):
    """Bar exists but belongs to a different event. -> 422."""


class ProductNotFoundError(Exception):
    """Product in allocate request doesn't exist. -> 404."""


class ProductArchivedError(Exception):
    """Cannot allocate archived product to stock. -> 422."""


class InsufficientStockError(Exception):
    """Consume requested more than current_qty. -> 422.

    Payload includes the max quantity available for a friendly UX.
    """
    def __init__(self, message: str, available: int, requested: int) -> None:
        super().__init__(message)
        self.available = available
        self.requested = requested


class ExcessiveReturnError(Exception):
    """Return would push returned_qty above allocated_qty. -> 422."""
    def __init__(self, message: str, max_returnable: int, requested: int) -> None:
        super().__init__(message)
        self.max_returnable = max_returnable
        self.requested = requested


class InvalidAdjustmentError(Exception):
    """Adjust payload would violate quantity invariants. -> 422.

    E.g. new_allocated_qty < current_qty, or new_current_qty > new_allocated_qty.
    """
    def __init__(self, message: str, violation: str) -> None:
        super().__init__(message)
        self.violation = violation


# ─── Service ──────────────────────────────────────────────────────────────────

class BarStockService:
    """All business logic for bar_stock operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = BarStockRepository(db)
        self.events = EventRepository(db)
        self.bars = BarRepository(db)
        self.products = ProductRepository(db)

    # ─── Read ─────────────────────────────────────────────────────────────────

    async def list_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        bar_id: UUID | None = None,
    ) -> Sequence[BarStock]:
        """List stock rows for an event. 404 if event doesn't exist in tenant.

        The 404 (vs silent empty list) surfaces typos early.
        """
        event = await self.events.get_by_id(tenant_id, event_id)
        if event is None:
            raise EventNotFoundError(f"Event {event_id} not found")
        return await self.repo.list_for_event(tenant_id, event_id, bar_id=bar_id)

    async def get_stock(
        self,
        tenant_id: UUID,
        stock_id: UUID,
    ) -> BarStock:
        stock = await self.repo.get_by_id(tenant_id, stock_id)
        if stock is None:
            raise BarStockNotFoundError(f"Stock row {stock_id} not found")
        return stock

    # ─── Allocate (create or topup) ──────────────────────────────────────────

    async def allocate(
        self,
        tenant_id: UUID,
        data: AllocateRequest,
    ) -> BarStock:
        """Transfer stock IN from warehouse.

        If a row exists for (event, bar, product): top it up
        (allocated_qty += qty, current_qty += qty).
        Otherwise: create a new row with allocated = current = qty.

        Full cross-module validation first (event, bar, product, coherence).
        """

        # 1. Event exists?
        event = await self.events.get_by_id(tenant_id, data.event_id)
        if event is None:
            raise EventNotFoundError(f"Event {data.event_id} not found")

        # 2. Bar exists + belongs to this event?
        bar = await self.bars.get_by_id(tenant_id, data.bar_id)
        if bar is None:
            raise BarNotFoundError(f"Bar {data.bar_id} not found")
        if bar.event_id != data.event_id:
            raise BarNotInEventError(
                f"Bar {data.bar_id} belongs to a different event"
            )

        # 3. Product exists and is active?
        product = await self.products.get_by_id(tenant_id, data.product_id)
        if product is None:
            raise ProductNotFoundError(f"Product {data.product_id} not found")
        if product.is_archived:
            raise ProductArchivedError(
                f"Product '{product.name}' is archived "
                f"and cannot be allocated to stock"
            )

        # 4. Does a stock row already exist for this triple?
        existing = await self.repo.find_by_triple(
            tenant_id, data.event_id, data.bar_id, data.product_id,
        )
        if existing is not None:
            # Top up: bump both allocated and current
            existing.allocated_qty += data.qty
            existing.current_qty += data.qty
            stock = await self.repo.save(existing)
        else:
            # Create new
            stock = await self.repo.create(
                tenant_id=tenant_id,
                event_id=data.event_id,
                bar_id=data.bar_id,
                product_id=data.product_id,
                allocated_qty=data.qty,
                current_qty=data.qty,
                returned_qty=0,
            )

        await self.db.commit()
        await publish_stock_change(
            tenant_id=stock.tenant_id,
            event_id=stock.event_id,
            bar_id=stock.bar_id,
            product_id=stock.product_id,
            change_type="allocate",
            extra={"allocated_qty": str(stock.allocated_qty), "current_qty": str(stock.current_qty)},
        )
        return stock

    # ─── Consume (decrement current_qty) ─────────────────────────────────────

    async def consume(
        self,
        tenant_id: UUID,
        stock_id: UUID,
        data: ConsumeRequest,
    ) -> BarStock:
        """Decrement current_qty. Used by bartenders and Slesh scan ingestion.

        Errors:
        - 404 if stock row doesn't exist
        - 422 InsufficientStockError if qty > current_qty
        """
        stock = await self.get_stock(tenant_id, stock_id)

        if data.qty > stock.current_qty:
            raise InsufficientStockError(
                f"Cannot consume {data.qty}: only {stock.current_qty} available.",
                available=stock.current_qty,
                requested=data.qty,
            )

        stock.current_qty -= data.qty
        stock = await self.repo.save(stock)
        await self.db.commit()
        await publish_stock_change(
            tenant_id=stock.tenant_id,
            event_id=stock.event_id,
            bar_id=stock.bar_id,
            product_id=stock.product_id,
            change_type="consume",
            extra={"qty": str(data.qty), "current_qty": str(stock.current_qty)},
        )
        return stock

    # ─── Return (increment returned_qty) ─────────────────────────────────────

    async def return_stock(
        self,
        tenant_id: UUID,
        stock_id: UUID,
        data: ReturnRequest,
    ) -> BarStock:
        """Transfer unused stock OUT to warehouse at event end.

        Increments returned_qty. Does NOT touch current_qty — the two
        are separate counters used for reconciliation.

        Errors:
        - 404 if stock row doesn't exist
        - 422 ExcessiveReturnError if new_returned > allocated
        """
        stock = await self.get_stock(tenant_id, stock_id)

        new_returned = stock.returned_qty + data.qty
        max_returnable = stock.allocated_qty - stock.returned_qty

        if new_returned > stock.allocated_qty:
            raise ExcessiveReturnError(
                f"Cannot return {data.qty}: max returnable is {max_returnable} "
                f"(allocated={stock.allocated_qty}, already returned={stock.returned_qty}).",
                max_returnable=max_returnable,
                requested=data.qty,
            )

        stock.returned_qty = new_returned
        stock = await self.repo.save(stock)
        await self.db.commit()
        await publish_stock_change(
            tenant_id=stock.tenant_id,
            event_id=stock.event_id,
            bar_id=stock.bar_id,
            product_id=stock.product_id,
            change_type="return",
            extra={"qty": str(data.qty), "returned_qty": str(stock.returned_qty)},
        )
        return stock

    # ─── Adjust (manual correction, audited) ─────────────────────────────────

    async def adjust(
        self,
        tenant_id: UUID,
        stock_id: UUID,
        data: AdjustRequest,
    ) -> BarStock:
        """Manual correction of any/all quantity columns.

        Enforces all invariants AFTER applying the new values:
        - new_current_qty <= new_allocated_qty
        - new_returned_qty <= new_allocated_qty
        - all non-negative (schema handles this via ge=0)

        reason is required at the schema level and is intended to be
        persisted to the audit log in Step 6 (stock_transactions ledger).
        For now we just use it for error messages but it's parsed.
        """
        stock = await self.get_stock(tenant_id, stock_id)

        # Compute the resulting state — omitted fields keep existing values
        new_allocated = (
            data.new_allocated_qty
            if data.new_allocated_qty is not None
            else stock.allocated_qty
        )
        new_current = (
            data.new_current_qty
            if data.new_current_qty is not None
            else stock.current_qty
        )
        new_returned = (
            data.new_returned_qty
            if data.new_returned_qty is not None
            else stock.returned_qty
        )

        # Validate resulting invariants
        if new_current > new_allocated:
            raise InvalidAdjustmentError(
                f"new_current_qty ({new_current}) exceeds "
                f"new_allocated_qty ({new_allocated}).",
                violation="current_gt_allocated",
            )
        if new_returned > new_allocated:
            raise InvalidAdjustmentError(
                f"new_returned_qty ({new_returned}) exceeds "
                f"new_allocated_qty ({new_allocated}).",
                violation="returned_gt_allocated",
            )

        stock.allocated_qty = new_allocated
        stock.current_qty = new_current
        stock.returned_qty = new_returned

        stock = await self.repo.save(stock)
        await self.db.commit()
        await publish_stock_change(
            tenant_id=stock.tenant_id,
            event_id=stock.event_id,
            bar_id=stock.bar_id,
            product_id=stock.product_id,
            change_type="write",
        )
        return stock
