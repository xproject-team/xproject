"""C2 regression coverage: cross-report revenue aggregates must count each
event ONCE — the latest ready version — never every version.

sum_lifetime_revenue, get_top_event_by_revenue (Portfolio KPI strip) and
_build_comparison's season-average all read stored data_json across ready
reports. Before this fix none of them deduplicated versions: regenerating
a report (v1 → v2, both status='ready') double-counted that event's
revenue in Lifetime Revenue and skewed the season average. Confirmed by
inspection during the Day 14 reports audit; latent until the first
regeneration happens in production.

Same DB-backed pattern as test_reports_extended_sections.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.modules.events.models import Event, EventStatus
from app.modules.reports.aggregator import ReportAggregator
from app.modules.reports.models import Report
from app.modules.reports.repository import ReportRepository
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_event,
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


async def _ready_report(
    session, tenant_id, event_id, *, version: int, revenue: str,
    language: str = "it", superseded_by=None,
) -> Report:
    r = Report(
        tenant_id=tenant_id, event_id=event_id, language=language,
        version=version, status="ready", superseded_by=superseded_by,
        data_json={"revenue_kpis": {"total_revenue": revenue}},
        generated_at=datetime.now(timezone.utc),
    )
    session.add(r)
    await session.flush()
    return r


async def test_sum_lifetime_revenue_counts_each_event_once():
    """Event A has v1 (superseded) + v2 ready; event B has one ready
    report. Lifetime revenue must be v2(A) + v1(B), never v1+v2+v1."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event_a = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            event_b = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await _complete_event(session, event_a)
            await _complete_event(session, event_b)

            v2 = await _ready_report(session, tenant.id, event_a.id, version=2, revenue="120.00")
            await _ready_report(
                session, tenant.id, event_a.id, version=1, revenue="100.00",
                superseded_by=v2.id,
            )
            await _ready_report(session, tenant.id, event_b.id, version=1, revenue="50.00")

            total = await ReportRepository(session).sum_lifetime_revenue(tenant.id)
            assert total == Decimal("170.00"), (
                f"expected 120 (latest of A) + 50 (B) = 170, got {total} — "
                "superseded versions must not be counted"
            )
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_get_top_event_by_revenue_uses_latest_version_per_event():
    """A superseded v1 with an inflated figure must not win Best Event —
    only the latest ready version of each event competes."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event_a = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            event_b = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await _complete_event(session, event_a)
            await _complete_event(session, event_b)

            v2 = await _ready_report(session, tenant.id, event_a.id, version=2, revenue="10.00")
            await _ready_report(
                session, tenant.id, event_a.id, version=1, revenue="999999.00",
                superseded_by=v2.id,
            )
            await _ready_report(session, tenant.id, event_b.id, version=1, revenue="50.00")

            top = await ReportRepository(session).get_top_event_by_revenue(tenant.id)
            assert top is not None
            _name, revenue = top
            assert revenue == Decimal("50.00"), (
                f"expected event B's 50.00 to win, got {revenue} — a superseded "
                "version's stale figure must never be the Best Event"
            )
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_comparison_season_avg_dedupes_versions():
    """Season average across 'every other ready report' must use one figure
    per event. A previous event with v1=100 and v2=200 contributes 200 once
    (n=1), not an average of 150 over n=2."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            prev_event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            curr_event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await _complete_event(session, prev_event, hours_ago=200)
            await _complete_event(session, curr_event, hours_ago=10)
            await session.execute(
                update(Event).where(Event.id == prev_event.id).values(
                    scheduled_at=datetime.now(timezone.utc) - timedelta(days=14),
                )
            )
            await session.flush()
            await session.refresh(prev_event)
            await session.refresh(curr_event)

            v2 = await _ready_report(session, tenant.id, prev_event.id, version=2, revenue="200.00")
            await _ready_report(
                session, tenant.id, prev_event.id, version=1, revenue="100.00",
                superseded_by=v2.id,
            )

            agg = ReportAggregator(session)
            revenue_kpis = await agg._build_revenue_kpis(tenant.id, curr_event.id, 8.0)
            guests = await agg._build_guests(tenant.id, curr_event.id)
            comparison = await agg._build_comparison(
                tenant.id, curr_event.id, curr_event, "it", revenue_kpis, guests,
            )

            assert comparison.available is True
            assert comparison.season_avg_n_events == 1, (
                "two versions of one event must count as ONE season event"
            )
            revenue_metric = next(
                m for m in comparison.metrics if m.label == "Total Revenue"
            )
            assert revenue_metric.season_avg_value == pytest.approx(200.0), (
                f"season avg must be the latest version's 200.00, got "
                f"{revenue_metric.season_avg_value}"
            )
            # The previous-event column must also use the latest version.
            assert revenue_metric.previous_event_value == pytest.approx(200.0)
        finally:
            await delete_tenant_cascade(session, tenant.id)
