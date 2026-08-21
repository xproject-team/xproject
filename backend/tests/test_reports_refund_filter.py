"""Regression coverage: ReportAggregator's revenue queries must exclude
refunded rows.

Since the Day 14 migration the euro figures come from event_orders: a
fully-refunded order (confirmed_line_count == 0) must not contribute to
total revenue or per-bar revenue — the same filter the dashboard and
RevenueBreakdownService apply (docs/revenue-calculation-bible.md).

_build_product_performance still reads stock_transactions lines (units /
per-product detail has no event_orders equivalent), so the original
line-level invariant stays covered too: "'refunded' for cup/bottle
returns. Aggregation queries filter on status='confirmed' so refunds
don't inflate revenue" — a refunded line keeps its price_cents (exactly
how order_ingester.py leaves it) and must still be excluded.

Same DB-backed pattern as test_reports_extended_sections.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.modules.events.models import Event, EventStatus
from app.modules.reports.aggregator import ReportAggregator
from app.modules.stock_transactions.models import TransactionSource
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_bar,
    make_event,
    make_event_order,
    make_product,
    make_stock_transaction,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def _complete_event(session, event: Event, *, hours_ago: int = 10) -> Event:
    started = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    ended = datetime.now(timezone.utc) - timedelta(hours=hours_ago - 8)
    await session.execute(
        update(Event)
        .where(Event.id == event.id)
        .values(status=EventStatus.COMPLETED, started_at=started, ended_at=ended)
    )
    await session.flush()
    await session.refresh(event)
    return event


async def _sale(
    session, tenant_id, event_id, bar_id, product_id, *,
    qty, price_cents, refunded=False,
):
    """A revenue-producing line, optionally left in the refunded state
    order_ingester.py actually produces: pos_line_status flipped, price_cents
    left populated (never cleared)."""
    st = await make_stock_transaction(
        session, tenant_id, event_id, bar_id, product_id,
        qty=Decimal(str(qty)), source=TransactionSource.SLESH_POS,
    )
    st.price_cents = price_cents
    if refunded:
        st.pos_line_status = "refunded"
    await session.flush()
    return st


async def test_revenue_kpis_excludes_fully_refunded_orders():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await _complete_event(session, event)
            bar = await make_bar(session, tenant.id, event.id)

            await make_event_order(
                session, tenant.id, event.id, bar_id=bar.id, fiscal_gross_cents=2000,
            )
            await make_event_order(  # fully refunded — must not count
                session, tenant.id, event.id, bar_id=bar.id, fiscal_gross_cents=5000,
                confirmed_line_count=0, refunded_line_count=1,
            )

            kpis = await ReportAggregator(session)._build_revenue_kpis(tenant.id, event.id, 8.0)

            assert kpis.total_revenue == Decimal("20.00")
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_bar_revenues_excludes_fully_refunded_orders():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await _complete_event(session, event)
            bar = await make_bar(session, tenant.id, event.id)

            await make_event_order(
                session, tenant.id, event.id, bar_id=bar.id, fiscal_gross_cents=3000,
            )
            await make_event_order(
                session, tenant.id, event.id, bar_id=bar.id, fiscal_gross_cents=9000,
                confirmed_line_count=0, refunded_line_count=1,
            )

            bar_revenues = await ReportAggregator(session)._build_bar_revenues(tenant.id, event.id)

            assert len(bar_revenues) == 1
            assert bar_revenues[0].revenue == Decimal("30.00")
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_product_performance_excludes_refunded_lines():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await _complete_event(session, event)
            bar = await make_bar(session, tenant.id, event.id)
            product = await make_product(session, tenant.id, name="Spritz")

            await _sale(session, tenant.id, event.id, bar.id, product.id, qty=5, price_cents=1000)
            await _sale(
                session, tenant.id, event.id, bar.id, product.id,
                qty=10, price_cents=1000, refunded=True,
            )

            pp = await ReportAggregator(session)._build_product_performance(tenant.id, event.id)

            assert len(pp.top_products) == 1
            assert pp.top_products[0].units_sold == 5
            assert pp.top_products[0].revenue_cents == 5000
        finally:
            await delete_tenant_cascade(session, tenant.id)
