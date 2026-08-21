"""Day 14 migration coverage: report euro figures come from event_orders
(the money-of-record, matching the dashboard header), while per-product
detail stays on stock_transactions.

Also covers the three service-layer fixes that shipped in the same pass:
  - C6: a language sibling is derived from the original's frozen
    snapshot, never re-aggregated — numbers stay identical across the
    language pair even after the measurement method changes.
  - C5: a failed regenerate must NOT mark the old ready report as
    superseded (that hid the good report behind a failed card).
  - The revenue_source marker + mixed_revenue_sources comparison flag.

Same DB-backed pattern as test_reports_extended_sections.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import update

from app.modules.events.models import Event, EventStatus
from app.modules.reports.aggregator import ReportAggregator
from app.modules.reports.models import Report
from app.modules.reports.service import ReportGenerationError, ReportService
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


async def _st_sale(session, tenant_id, event_id, bar_id, product_id, *, qty, price_cents):
    st = await make_stock_transaction(
        session, tenant_id, event_id, bar_id, product_id,
        qty=Decimal(str(qty)), source=TransactionSource.SLESH_POS,
    )
    st.price_cents = price_cents
    await session.flush()
    return st


# ─── Revenue KPIs: event_orders is the money-of-record ───────────────────────

async def test_total_revenue_sums_confirmed_event_orders_not_stock_lines():
    """Headline = SUM(fiscal_gross_cents) over confirmed orders, unmapped
    included, fully-refunded excluded — and stock_transactions lines no
    longer contribute euros (they'd double-count the same sales)."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await _complete_event(session, event)
            bar = await make_bar(session, tenant.id, event.id)

            await make_event_order(session, tenant.id, event.id, bar_id=bar.id, fiscal_gross_cents=1500)
            await make_event_order(session, tenant.id, event.id, bar_id=None, fiscal_gross_cents=2500)  # unmapped
            await make_event_order(  # fully refunded — excluded
                session, tenant.id, event.id, bar_id=bar.id,
                fiscal_gross_cents=9999, confirmed_line_count=0, refunded_line_count=2,
            )
            # A stock line for the same event: units-only detail, no euros.
            product = await make_product(session, tenant.id, name="Spritz")
            await _st_sale(session, tenant.id, event.id, bar.id, product.id, qty=3, price_cents=77700)

            kpis = await ReportAggregator(session)._build_revenue_kpis(tenant.id, event.id, 8.0)

            assert kpis.total_revenue == Decimal("40.00")
            assert kpis.unmapped_revenue == Decimal("25.00")
            assert kpis.revenue_per_hour == Decimal("40.00") / Decimal("8.0")
            # Only one bar sold; unmapped money must not be smeared into
            # the per-bar average: 15.00 / 1 bar, not 40.00 / 1.
            assert kpis.revenue_per_bar_avg == Decimal("15.00")
            # Per-product detail still comes from stock_transactions.
            assert kpis.top_product_name == "Spritz"
            assert kpis.top_product_units == 3
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_peak_hour_uses_slesh_order_timestamps():
    """Peak hour buckets on created_at_slesh (true order time), not on the
    poller's ingestion timestamp (median lag 25–48s, tail 6.6h)."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await _complete_event(session, event)
            bar = await make_bar(session, tenant.id, event.id)

            quiet_hour = datetime(2026, 8, 1, 21, 15, tzinfo=timezone.utc)
            peak_hour = datetime(2026, 8, 1, 23, 5, tzinfo=timezone.utc)
            await make_event_order(
                session, tenant.id, event.id, bar_id=bar.id,
                fiscal_gross_cents=1000, created_at_slesh=quiet_hour,
            )
            for minute in (5, 20, 40):
                await make_event_order(
                    session, tenant.id, event.id, bar_id=bar.id,
                    fiscal_gross_cents=2000,
                    created_at_slesh=peak_hour.replace(minute=minute),
                )

            kpis = await ReportAggregator(session)._build_revenue_kpis(tenant.id, event.id, 8.0)

            assert kpis.peak_hour_start is not None
            assert kpis.peak_hour_start.astimezone(timezone.utc).hour == 23
            assert kpis.peak_hour_revenue == Decimal("60.00")
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_bar_revenues_from_event_orders_with_unmapped_remainder():
    """Per-bar rows come from event_orders grouped by bar; pct is of the
    FULL total (incl. unmapped), so rows sum below 100% rather than
    silently redistributing unattributable money."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await _complete_event(session, event)
            bar_a = await make_bar(session, tenant.id, event.id)
            bar_b = await make_bar(session, tenant.id, event.id)

            await make_event_order(session, tenant.id, event.id, bar_id=bar_a.id, fiscal_gross_cents=6000)
            await make_event_order(session, tenant.id, event.id, bar_id=bar_a.id, fiscal_gross_cents=1000)
            await make_event_order(session, tenant.id, event.id, bar_id=bar_b.id, fiscal_gross_cents=2000)
            await make_event_order(session, tenant.id, event.id, bar_id=None, fiscal_gross_cents=1000)

            rows = await ReportAggregator(session)._build_bar_revenues(tenant.id, event.id)

            assert [r.bar_id for r in rows] == [bar_a.id, bar_b.id]
            assert rows[0].revenue == Decimal("70.00")
            assert rows[0].transactions_count == 2  # orders, not lines
            assert rows[0].rank == 1
            # 70 of 100 total (which includes the 10 unmapped) = 70%.
            assert rows[0].revenue_pct == pytest.approx(70.0)
            assert rows[1].revenue_pct == pytest.approx(20.0)
        finally:
            await delete_tenant_cascade(session, tenant.id)


# ─── Full pipeline: marker + language sibling + regenerate ordering ──────────

async def test_generated_report_carries_event_orders_marker():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await _complete_event(session, event)
            bar = await make_bar(session, tenant.id, event.id)
            await make_event_order(session, tenant.id, event.id, bar_id=bar.id, fiscal_gross_cents=5000)

            service = ReportService(session)
            report = await service.generate_on_demand(tenant.id, event.id, "it")

            assert report.status == "ready"
            assert report.data_json["revenue_source"] == "event_orders"
            assert report.data_json["revenue_kpis"]["total_revenue"] == "50.00"
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_language_sibling_reuses_frozen_snapshot_never_reaggregates():
    """C6: toggling language on an existing report must derive the sibling
    from the ORIGINAL's data_json. If it re-aggregated, a report generated
    before a method change would show different numbers per language under
    the same version label."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await _complete_event(session, event)
            bar = await make_bar(session, tenant.id, event.id)
            await make_event_order(session, tenant.id, event.id, bar_id=bar.id, fiscal_gross_cents=5000)

            service = ReportService(session)
            original = await service.generate_on_demand(tenant.id, event.id, "it")

            # The data has since changed (a late order arrives). A sibling
            # generated by re-aggregation would see 90.00; the frozen
            # snapshot says 50.00.
            await make_event_order(session, tenant.id, event.id, bar_id=bar.id, fiscal_gross_cents=4000)

            with patch.object(
                service.aggregator, "aggregate",
                side_effect=AssertionError("sibling generation must not re-aggregate"),
            ):
                sibling = await service.get_report_in_language(
                    tenant.id, original.id, "en",
                )

            assert sibling.id != original.id
            assert sibling.language == "en"
            assert sibling.version == original.version
            assert sibling.status == "ready"
            assert (
                sibling.data_json["revenue_kpis"]["total_revenue"]
                == original.data_json["revenue_kpis"]["total_revenue"]
                == "50.00"
            )
            # Narrative is re-rendered in the sibling's language.
            assert sibling.data_json["language"] == "en"
            assert sibling.pdf_bytes is not None
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_failed_regenerate_does_not_supersede_the_ready_report():
    """C5: superseded_by is set only AFTER the new version generates
    successfully. A failed regenerate must leave the old ready report
    exactly as it was — still the visible, authoritative version."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await _complete_event(session, event)
            bar = await make_bar(session, tenant.id, event.id)
            await make_event_order(session, tenant.id, event.id, bar_id=bar.id, fiscal_gross_cents=5000)

            service = ReportService(session)
            original = await service.generate_on_demand(tenant.id, event.id, "it")

            with patch.object(
                service.aggregator, "aggregate",
                side_effect=RuntimeError("boom"),
            ):
                with pytest.raises(ReportGenerationError):
                    await service.regenerate(tenant.id, original.id)

            await session.refresh(original)
            assert original.superseded_by is None, (
                "a failed regenerate must not mark the good report superseded"
            )

            # A successful regenerate DOES supersede.
            new = await service.regenerate(tenant.id, original.id)
            await session.refresh(original)
            assert original.superseded_by == new.id
            assert new.status == "ready"
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_comparison_flags_mixed_revenue_sources_against_old_reports():
    """A comparison whose previous event was measured with the old method
    (no revenue_source in its data_json) must say so — the delta carries
    a definitional component and the narrative suppresses its
    revenue-vs-previous sentence."""
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
            guests = await agg._build_guests(tenant.id, curr_event.id)
            comparison = await agg._build_comparison(
                tenant.id, curr_event.id, curr_event, "it", revenue_kpis, guests,
            )

            assert comparison.available is True
            assert comparison.mixed_revenue_sources is True
            revenue_metric = next(m for m in comparison.metrics if m.label == "Total Revenue")
            assert revenue_metric.unit == "eur"
        finally:
            await delete_tenant_cascade(session, tenant.id)
