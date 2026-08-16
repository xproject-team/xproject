"""Tests for RevenueBreakdownService's food-vendor-share calculation.

Regression coverage for the bug where `int(event.food_revenue_share_pct or
30)` collapsed both NULL and an explicit 0 to 30, contradicting the model's
own documented contract (NULL = 100, owner keeps everything) — and for the
float-truncation in `int(food_total * share_pct / 100)`, replaced with
Decimal + ROUND_HALF_UP.

Same fixture style as test_event_kpi_summary.py (EventKpiSummaryService's
sibling service, which already implements the correct None-check this file
brings RevenueBreakdownService in line with).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.modules.events.models import EventOrder
from app.modules.events.revenue_breakdown_service import RevenueBreakdownService
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_bar,
    make_event,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def _order(
    session, tenant_id, event_id, bar_id, *, subtotal_cents,
) -> EventOrder:
    """A minimal EventOrder row on a food bar — the sole input to food_total
    in RevenueBreakdownService.compute()."""
    order = EventOrder(
        tenant_id=tenant_id,
        event_id=event_id,
        slesh_order_id=f"test-{uuid.uuid4().hex[:12]}",
        slesh_shop_id=None,
        bar_id=bar_id,
        order_type="experience",
        subtotal_cents=subtotal_cents,
        vat_cents=0,
        deposit_cents=0,
        fiscal_gross_cents=subtotal_cents,
        fiscal_net_cents=subtotal_cents,
        discount_cents=0,
        cart_line_count=1,
        confirmed_line_count=1,
        refunded_line_count=0,
        created_at_slesh=datetime.now(timezone.utc),
    )
    session.add(order)
    await session.flush()
    return order


async def test_null_share_owner_keeps_100_pct():
    """NULL food_revenue_share_pct = 100 (no split) per the model's own
    documented contract — the field is left unset by default."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)  # share defaults to NULL
            food_bar = await make_bar(session, tenant.id, ev.id, bar_type="food")
            await _order(session, tenant.id, ev.id, food_bar.id, subtotal_cents=10000)

            result = await RevenueBreakdownService(session).compute(tenant.id, ev.id)

            assert result.owner_waterfall.food_owner_share_pct == 100
            assert result.owner_waterfall.food_vendor_share_pct == 0
            assert result.owner_waterfall.food_owner_share_eur == Decimal("100.00")
            assert result.owner_waterfall.minus_food_vendor_share_eur == Decimal("0.00")
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_explicit_zero_share_vendor_keeps_all():
    """An explicit 0 must stay 0 (owner keeps nothing) — not silently
    fall back to the 30% default, which is what `x or 30` did."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            ev.food_revenue_share_pct = 0
            await session.flush()
            food_bar = await make_bar(session, tenant.id, ev.id, bar_type="food")
            await _order(session, tenant.id, ev.id, food_bar.id, subtotal_cents=10000)

            result = await RevenueBreakdownService(session).compute(tenant.id, ev.id)

            assert result.owner_waterfall.food_owner_share_pct == 0
            assert result.owner_waterfall.food_vendor_share_pct == 100
            assert result.owner_waterfall.food_owner_share_eur == Decimal("0.00")
            assert result.owner_waterfall.minus_food_vendor_share_eur == Decimal("100.00")
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_explicit_30_share_matches_sundance_default():
    """Explicit 30% (the real-world Sundance configuration) still splits
    correctly — no regression on the common case."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            ev.food_revenue_share_pct = 30
            await session.flush()
            food_bar = await make_bar(session, tenant.id, ev.id, bar_type="food")
            await _order(session, tenant.id, ev.id, food_bar.id, subtotal_cents=6000)

            result = await RevenueBreakdownService(session).compute(tenant.id, ev.id)

            assert result.owner_waterfall.food_owner_share_pct == 30
            assert result.owner_waterfall.food_vendor_share_pct == 70
            assert result.owner_waterfall.food_owner_share_eur == Decimal("18.00")
            assert result.owner_waterfall.minus_food_vendor_share_eur == Decimal("42.00")
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_share_rounds_half_up_not_truncated():
    """food_total * share_pct / 100 = 333 * 50 / 100 = 166.5 exactly.
    int() truncation gives 166 (owner short-changed by half a cent);
    Decimal + ROUND_HALF_UP correctly gives 167."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            ev.food_revenue_share_pct = 50
            await session.flush()
            food_bar = await make_bar(session, tenant.id, ev.id, bar_type="food")
            await _order(session, tenant.id, ev.id, food_bar.id, subtotal_cents=333)

            result = await RevenueBreakdownService(session).compute(tenant.id, ev.id)

            assert result.owner_waterfall.food_owner_share_eur == Decimal("1.67")
            assert result.owner_waterfall.minus_food_vendor_share_eur == Decimal("1.66")
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()
