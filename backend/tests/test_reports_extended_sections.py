"""Tests for the Reports feature extension (5 new sections, 2026-07-31):
A. Guests, B. Forecast vs. Actual, C. Event-over-Event Comparison,
D. Revenue Decomposition, E. Top/Lowest-Selling Products.

Follows the project's established DB-backed unit-test pattern (direct
service/aggregator calls against the real dev Postgres via TestSessionLocal
+ tests.fixtures.alerts.factories) — NOT the httpx AsyncClient harness,
which test_reports_flow.py documents as incompatible with DB-backed tests
in this asyncio/pytest-asyncio version.

Each new ReportAggregator slice is independently gracefully-degrading —
these tests cover both the "data present" and "data absent" paths, since
"absent" is the NORMAL state for an event that predates this feature or
hasn't finished customer-feature population yet, not an error condition.

Section B (Forecast vs. Actual) is covered in test_reports_forecast_section.py
— it needs a trained ModelArtifact (via retrain_demand_model), a heavier
fixture kept in its own file.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.modules.customer_analytics.models import CustomerSession
from app.modules.events.models import Event, EventStatus
from app.modules.reports.aggregator import ReportAggregator
from app.modules.reports.models import Report
from app.modules.reports.repository import ReportRepository
from app.modules.stock_transactions.models import TransactionSource
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_bar,
    make_event,
    make_product,
    make_stock_transaction,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def _complete_event(session, event: Event, *, hours_ago: int = 10) -> Event:
    """Backdate + complete an event so the aggregator's EventNotCompletedError
    gate doesn't fire — every new slice requires a COMPLETED event with
    started_at/ended_at populated."""
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


async def _make_customer_session(
    session, tenant_id, event_id, *, customer_key, total_spend_cents,
    is_registered=True, order_count=1,
) -> CustomerSession:
    now = datetime.now(timezone.utc)
    cs = CustomerSession(
        tenant_id=tenant_id, event_id=event_id, customer_key=customer_key,
        first_order_at=now, last_order_at=now, session_minutes=Decimal("30.0"),
        order_count=order_count, total_spend_cents=total_spend_cents,
        avg_order_cents=total_spend_cents // order_count if order_count else 0,
        distinct_bars=1, is_registered=is_registered,
    )
    session.add(cs)
    await session.flush()
    return cs


async def _sale(session, tenant_id, event_id, bar_id, product_id, *, qty, price_cents):
    st = await make_stock_transaction(
        session, tenant_id, event_id, bar_id, product_id,
        qty=Decimal(str(qty)), source=TransactionSource.SLESH_POS,
    )
    st.price_cents = price_cents
    await session.flush()
    return st


# ─── Section A: Guests ────────────────────────────────────────────────────────

async def test_build_guests_unavailable_when_no_sessions():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        await _complete_event(session, event)

        guests = await ReportAggregator(session)._build_guests(tenant.id, event.id)
        assert guests.available is False
        assert guests.unavailable_reason is not None
        assert guests.identified_total == 0

        await delete_tenant_cascade(session, tenant.id)


async def test_build_guests_counts_segments_and_returning_split():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event_a = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        event_b = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        await _complete_event(session, event_a)
        await _complete_event(session, event_b)

        # event_a: one whale (>= 6800c), one light (<= 2400c), one regular.
        await _make_customer_session(session, tenant.id, event_a.id, customer_key="cust-1", total_spend_cents=7000)
        await _make_customer_session(session, tenant.id, event_a.id, customer_key="cust-2", total_spend_cents=1000)
        await _make_customer_session(session, tenant.id, event_a.id, customer_key="cust-3", total_spend_cents=4000)
        # cust-1 also attended event_b -> returning, from event_a's perspective.
        await _make_customer_session(session, tenant.id, event_b.id, customer_key="cust-1", total_spend_cents=3000)

        guests = await ReportAggregator(session)._build_guests(tenant.id, event_a.id)
        assert guests.available is True
        assert guests.identified_total == 3
        assert guests.whale_count == 1
        assert guests.light_count == 1
        assert guests.regular_count == 1
        assert guests.returning_count == 1
        assert guests.new_count == 2

        await delete_tenant_cascade(session, tenant.id)


# ─── Section D: Revenue Decomposition ─────────────────────────────────────────

async def test_build_revenue_decomposition_unavailable_without_guests():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        await _complete_event(session, event)

        agg = ReportAggregator(session)
        guests = await agg._build_guests(tenant.id, event.id)
        revenue_kpis = await agg._build_revenue_kpis(tenant.id, event.id, 8.0)
        rd = await agg._build_revenue_decomposition(tenant.id, event, guests, revenue_kpis)
        assert rd.available is False

        await delete_tenant_cascade(session, tenant.id)


async def test_build_revenue_decomposition_computes_estimate_derived_rate():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        await _complete_event(session, event)
        # make_event's factory default sets expected_guest_count=100.

        await _make_customer_session(
            session, tenant.id, event.id, customer_key="cust-1",
            total_spend_cents=5000, order_count=2,
        )
        await _make_customer_session(
            session, tenant.id, event.id, customer_key="cust-2",
            total_spend_cents=3000, order_count=1,
        )

        agg = ReportAggregator(session)
        guests = await agg._build_guests(tenant.id, event.id)
        revenue_kpis = await agg._build_revenue_kpis(tenant.id, event.id, 8.0)
        rd = await agg._build_revenue_decomposition(tenant.id, event, guests, revenue_kpis)

        assert rd.available is True
        assert rd.estimated_attendance == 100
        assert rd.purchasers == 2
        # 2 purchasers / 100 estimated attendance = 2.0%
        assert rd.purchase_rate_pct == pytest.approx(2.0, abs=0.01)
        # (2+1) orders / 2 purchasers = 1.5
        assert rd.orders_per_purchaser == pytest.approx(1.5, abs=0.01)
        # (5000+3000) cents / 3 orders = 2666.67 -> rounds to 2667
        assert rd.average_order_value_cents == 2667

        await delete_tenant_cascade(session, tenant.id)


# ─── Section E: Top / Lowest-Selling Products ─────────────────────────────────

async def test_build_product_performance_excludes_zero_sold_and_ranks_correctly():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        await _complete_event(session, event)
        bar = await make_bar(session, tenant.id, event.id)

        best = await make_product(session, tenant.id, name="Spritz")
        worst = await make_product(session, tenant.id, name="Rare Wine")
        await make_product(session, tenant.id, name="Never Sold")  # excluded — zero rows

        await _sale(session, tenant.id, event.id, bar.id, best.id, qty=50, price_cents=1000)
        await _sale(session, tenant.id, event.id, bar.id, worst.id, qty=2, price_cents=1000)

        pp = await ReportAggregator(session)._build_product_performance(tenant.id, event.id)

        top_names = [r.product_name for r in pp.top_products]
        lowest_names = [r.product_name for r in pp.lowest_selling_products]
        assert "Never Sold" not in top_names
        assert "Never Sold" not in lowest_names
        assert top_names[0] == "Spritz"
        assert lowest_names[0] == "Rare Wine"
        assert pp.top_products[0].units_sold == 50
        assert pp.lowest_selling_products[0].units_sold == 2

        await delete_tenant_cascade(session, tenant.id)


# ─── Section C: Event-over-Event Comparison ───────────────────────────────────

async def test_build_comparison_unavailable_with_no_prior_events():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        await _complete_event(session, event)

        agg = ReportAggregator(session)
        revenue_kpis = await agg._build_revenue_kpis(tenant.id, event.id, 8.0)
        guests = await agg._build_guests(tenant.id, event.id)
        comparison = await agg._build_comparison(
            tenant.id, event.id, event, "it", revenue_kpis, guests,
        )
        assert comparison.available is False

        await delete_tenant_cascade(session, tenant.id)


async def test_build_comparison_computes_revenue_delta_and_flags_missing_guest_data():
    """A prior report that predates this feature (no 'guests' key in its
    data_json) must still compare on revenue, and must say plainly that
    guest comparison isn't available for it — not silently drop the row,
    not backfill it (plan approval, Section C)."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        prev_event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        curr_event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        await _complete_event(session, prev_event, hours_ago=200)
        await _complete_event(session, curr_event, hours_ago=10)
        # prev_event must be scheduled before curr_event for the "previous
        # event" query (ORDER BY Event.scheduled_at DESC ... < current).
        await session.execute(
            update(Event).where(Event.id == prev_event.id).values(
                scheduled_at=datetime.now(timezone.utc) - timedelta(days=14),
                name="Sundance 5Jul",
            )
        )
        await session.execute(
            update(Event).where(Event.id == curr_event.id).values(
                scheduled_at=datetime.now(timezone.utc),
            )
        )
        await session.flush()
        await session.refresh(prev_event)
        await session.refresh(curr_event)

        # Old-shape data_json — no "guests" key at all, matching a report
        # generated before this feature shipped.
        old_report = Report(
            tenant_id=tenant.id, event_id=prev_event.id, language="it",
            version=1, status="ready",
            data_json={"revenue_kpis": {"total_revenue": "20000.00"}},
            generated_at=datetime.now(timezone.utc),
        )
        session.add(old_report)
        await session.flush()

        agg = ReportAggregator(session)
        revenue_kpis = await agg._build_revenue_kpis(tenant.id, curr_event.id, 8.0)
        # Force a known current revenue via a real sale.
        bar = await make_bar(session, tenant.id, curr_event.id)
        product = await make_product(session, tenant.id, name="Spritz")
        await _sale(session, tenant.id, curr_event.id, bar.id, product.id, qty=1, price_cents=2200000)
        revenue_kpis = await agg._build_revenue_kpis(tenant.id, curr_event.id, 8.0)

        guests = await agg._build_guests(tenant.id, curr_event.id)
        comparison = await agg._build_comparison(
            tenant.id, curr_event.id, curr_event, "it", revenue_kpis, guests,
        )

        assert comparison.available is True
        assert comparison.previous_event_name == "Sundance 5Jul"
        revenue_metric = next(m for m in comparison.metrics if m.label == "Total Revenue")
        # current 22000.00 vs previous 20000.00 -> +10%
        assert revenue_metric.previous_event_delta_pct == pytest.approx(10.0, abs=0.1)
        assert comparison.guest_metrics_available_from is not None
        assert not any(m.label == "Identified Guests" for m in comparison.metrics)

        await delete_tenant_cascade(session, tenant.id)


# ─── list_events_needing_reports: the population-ordering guarantee ──────────

async def test_list_events_needing_reports_waits_then_forces_after_cutoff():
    """Between grace_minutes and force_after_minutes, an event whose
    customer-features population hasn't finished yet must NOT be
    returned. Past force_after_minutes it must be returned regardless —
    the hard cutoff that stops a stuck population job from permanently
    blocking a report (CAVEAT 1)."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        mid_window_event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        past_cutoff_event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)

        now = datetime.now(timezone.utc)
        await session.execute(
            update(Event).where(Event.id == mid_window_event.id).values(
                started_at=now - timedelta(minutes=200),
                ended_at=now - timedelta(minutes=20),  # 20 min ago: past grace(15), before force(30)
            )
        )
        await session.execute(
            update(Event).where(Event.id == past_cutoff_event.id).values(
                started_at=now - timedelta(minutes=200),
                ended_at=now - timedelta(minutes=45),  # past force_after_minutes(30) too
            )
        )
        await session.flush()

        due = await ReportRepository(session).list_events_needing_reports(
            grace_minutes=15, force_after_minutes=30,
        )
        due_ids = {e.id for e in due}

        assert mid_window_event.id not in due_ids, (
            "event within the grace..force window with no customer_sessions "
            "yet must not be returned — the population job gets one more "
            "cron tick to finish"
        )
        assert past_cutoff_event.id in due_ids, (
            "event past force_after_minutes must be returned regardless of "
            "customer_sessions state — the hard cutoff must never let a "
            "stuck population job block the report forever"
        )

        await delete_tenant_cascade(session, tenant.id)


async def test_list_events_needing_reports_does_not_wait_once_population_ready():
    """Once customer_sessions exist for the event, it's eligible immediately
    — no need to wait out even the force_after_minutes window."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        now = datetime.now(timezone.utc)
        await session.execute(
            update(Event).where(Event.id == event.id).values(
                started_at=now - timedelta(minutes=200),
                ended_at=now - timedelta(minutes=20),  # only just past grace, well before force
            )
        )
        await session.flush()
        await _make_customer_session(session, tenant.id, event.id, customer_key="cust-1", total_spend_cents=1000)

        due = await ReportRepository(session).list_events_needing_reports(
            grace_minutes=15, force_after_minutes=30,
        )
        assert event.id in {e.id for e in due}

        await delete_tenant_cascade(session, tenant.id)
