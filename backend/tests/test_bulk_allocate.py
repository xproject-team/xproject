"""Bulk allocation tests (Phase C4 — Sundance 1 manual inventory).

Covers POST /bar-stock/bulk-allocate service logic:
- 'set' mode creates rows with allocated = current = qty
- 'set' mode is idempotent (re-posting same payload → all unchanged)
- 'set' mode applies deltas to current_qty, clamped at 0
- 'topup' mode matches single-allocate semantics (+= qty)
- all-or-nothing: one invalid item rejects the whole batch
- duplicate (bar, product) pairs in payload rejected
- bar from another event rejected
- 'set' target below returned_qty rejected

Pattern: disposable tenant per test via alerts factories, cleaned up in
finally with delete_tenant_cascade (service commits internally, so
SAVEPOINT isolation does not apply here).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.bar_stock.models import BarStock
from app.modules.events.models import EventStatus
from app.modules.bar_stock.schemas import BulkAllocateItem, BulkAllocateRequest
from app.modules.bar_stock.service import (
    BarStockService,
    BulkAllocationValidationError,
)
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_bar,
    make_bar_stock,
    make_event,
    make_product,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal


async def _count_rows(session, tenant_id) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(BarStock).where(
                BarStock.tenant_id == tenant_id
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_bulk_set_creates_rows():
    """set mode on empty stock: every item creates a row, allocated=current=qty."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id)
            bar1 = await make_bar(session, tenant.id, event.id)
            bar2 = await make_bar(session, tenant.id, event.id)
            p1 = await make_product(session, tenant.id)
            p2 = await make_product(session, tenant.id)

            svc = BarStockService(session)
            result = await svc.bulk_allocate(tenant.id, BulkAllocateRequest(
                event_id=event.id,
                mode="set",
                items=[
                    BulkAllocateItem(bar_id=bar1.id, product_id=p1.id, qty=120),
                    BulkAllocateItem(bar_id=bar1.id, product_id=p2.id, qty=60),
                    BulkAllocateItem(bar_id=bar2.id, product_id=p1.id, qty=40),
                    BulkAllocateItem(bar_id=bar2.id, product_id=p2.id, qty=0),
                ],
            ))

            assert result["created"] == 3      # qty=0 with no row → skipped
            assert result["updated"] == 0
            assert result["unchanged"] == 1
            assert await _count_rows(session, tenant.id) == 3
            for row in result["rows"]:
                assert row.allocated_qty == row.current_qty
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_bulk_set_is_idempotent():
    """Re-posting the identical 'set' payload changes nothing."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id)
            bar = await make_bar(session, tenant.id, event.id)
            p1 = await make_product(session, tenant.id)
            p2 = await make_product(session, tenant.id)

            payload = BulkAllocateRequest(
                event_id=event.id,
                mode="set",
                items=[
                    BulkAllocateItem(bar_id=bar.id, product_id=p1.id, qty=100),
                    BulkAllocateItem(bar_id=bar.id, product_id=p2.id, qty=50),
                ],
            )
            svc = BarStockService(session)
            first = await svc.bulk_allocate(tenant.id, payload)
            second = await svc.bulk_allocate(tenant.id, payload)

            assert first["created"] == 2
            assert second["created"] == 0
            assert second["updated"] == 0
            assert second["unchanged"] == 2
            for row in second["rows"]:
                assert int(row.allocated_qty) in (100, 50)
                assert row.allocated_qty == row.current_qty
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_bulk_set_applies_delta_and_clamps_current():
    """set target moves allocated to target; current shifts by delta, floor 0."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id)
            bar = await make_bar(session, tenant.id, event.id)
            prod = await make_product(session, tenant.id)
            # Mid-event state: 100 allocated, 30 left (70 consumed)
            await make_bar_stock(
                session, tenant.id, event.id, bar.id, prod.id,
                allocated_qty=Decimal("100"), current_qty=Decimal("30"),
            )

            svc = BarStockService(session)
            # Lower target to 50 → delta -50 → current max(0, 30-50) = 0
            result = await svc.bulk_allocate(tenant.id, BulkAllocateRequest(
                event_id=event.id,
                mode="set",
                items=[BulkAllocateItem(bar_id=bar.id, product_id=prod.id, qty=50)],
            ))
            row = result["rows"][0]
            assert result["updated"] == 1
            assert int(row.allocated_qty) == 50
            assert int(row.current_qty) == 0

            # Raise target to 80 → delta +30 → current 0+30 = 30
            result = await svc.bulk_allocate(tenant.id, BulkAllocateRequest(
                event_id=event.id,
                mode="set",
                items=[BulkAllocateItem(bar_id=bar.id, product_id=prod.id, qty=80)],
            ))
            row = result["rows"][0]
            assert int(row.allocated_qty) == 80
            assert int(row.current_qty) == 30
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_bulk_topup_matches_single_allocate_semantics():
    """topup mode: allocated += qty AND current += qty, create when missing."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id)
            bar = await make_bar(session, tenant.id, event.id)
            p1 = await make_product(session, tenant.id)
            p2 = await make_product(session, tenant.id)
            await make_bar_stock(
                session, tenant.id, event.id, bar.id, p1.id,
                allocated_qty=Decimal("100"), current_qty=Decimal("40"),
            )

            svc = BarStockService(session)
            result = await svc.bulk_allocate(tenant.id, BulkAllocateRequest(
                event_id=event.id,
                mode="topup",
                items=[
                    BulkAllocateItem(bar_id=bar.id, product_id=p1.id, qty=20),
                    BulkAllocateItem(bar_id=bar.id, product_id=p2.id, qty=10),
                ],
            ))
            assert result["updated"] == 1
            assert result["created"] == 1
            by_product = {r.product_id: r for r in result["rows"]}
            assert int(by_product[p1.id].allocated_qty) == 120
            assert int(by_product[p1.id].current_qty) == 60
            assert int(by_product[p2.id].allocated_qty) == 10
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_bulk_all_or_nothing_on_invalid_item():
    """One bad product among good items → error report, ZERO rows persisted."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id)
            bar = await make_bar(session, tenant.id, event.id)
            good = await make_product(session, tenant.id)
            import uuid as _uuid
            ghost = _uuid.uuid4()

            svc = BarStockService(session)
            with pytest.raises(BulkAllocationValidationError) as exc:
                await svc.bulk_allocate(tenant.id, BulkAllocateRequest(
                    event_id=event.id,
                    mode="set",
                    items=[
                        BulkAllocateItem(bar_id=bar.id, product_id=good.id, qty=50),
                        BulkAllocateItem(bar_id=bar.id, product_id=ghost, qty=50),
                    ],
                ))
            errs = exc.value.errors
            assert len(errs) == 1
            assert errs[0].index == 1
            assert errs[0].error == "product not found"
            assert await _count_rows(session, tenant.id) == 0
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_bulk_duplicate_pair_rejected():
    """Same (bar, product) twice in one payload → indexed duplicate error."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id)
            bar = await make_bar(session, tenant.id, event.id)
            prod = await make_product(session, tenant.id)

            svc = BarStockService(session)
            with pytest.raises(BulkAllocationValidationError) as exc:
                await svc.bulk_allocate(tenant.id, BulkAllocateRequest(
                    event_id=event.id,
                    mode="set",
                    items=[
                        BulkAllocateItem(bar_id=bar.id, product_id=prod.id, qty=10),
                        BulkAllocateItem(bar_id=bar.id, product_id=prod.id, qty=20),
                    ],
                ))
            assert exc.value.errors[0].index == 1
            assert "duplicate" in exc.value.errors[0].error
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_bulk_bar_from_other_event_rejected():
    """A bar belonging to a different event is rejected."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event_a = await make_event(session, tenant.id)
            event_b = await make_event(session, tenant.id, status=EventStatus.DRAFT)
            bar_b = await make_bar(session, tenant.id, event_b.id)
            prod = await make_product(session, tenant.id)

            svc = BarStockService(session)
            with pytest.raises(BulkAllocationValidationError) as exc:
                await svc.bulk_allocate(tenant.id, BulkAllocateRequest(
                    event_id=event_a.id,
                    mode="set",
                    items=[BulkAllocateItem(bar_id=bar_b.id, product_id=prod.id, qty=10)],
                ))
            assert "different event" in exc.value.errors[0].error
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_bulk_set_below_returned_qty_rejected():
    """set target below returned_qty would break the DB CHECK — rejected upfront."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id)
            bar = await make_bar(session, tenant.id, event.id)
            prod = await make_product(session, tenant.id)
            await make_bar_stock(
                session, tenant.id, event.id, bar.id, prod.id,
                allocated_qty=Decimal("100"), current_qty=Decimal("20"),
                returned_qty=Decimal("10"),
            )

            svc = BarStockService(session)
            with pytest.raises(BulkAllocationValidationError) as exc:
                await svc.bulk_allocate(tenant.id, BulkAllocateRequest(
                    event_id=event.id,
                    mode="set",
                    items=[BulkAllocateItem(bar_id=bar.id, product_id=prod.id, qty=5)],
                ))
            assert "returned_qty" in exc.value.errors[0].error
        finally:
            await delete_tenant_cascade(session, tenant.id)
