"""--force on the regeneration script: bypass ONLY the revenue_source
idempotency skip.

The script skips regeneration when the latest ready IT report already
carries revenue_source='event_orders' — correct for the migration run,
but it makes a deliberate re-regeneration (e.g. after event renames,
so the frozen PDFs carry the clean names) impossible. --force must
override exactly that one guard; version allocation, sibling
derivation, supersede chaining, and the three inline verifications all
stay in force.

Written FIRST, against the script without a force parameter, per the
project's failing-test-before-fix rule.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.modules.events.models import Event, EventStatus
from app.modules.reports.repository import ReportRepository
from app.modules.reports.service import ReportService
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_bar,
    make_event,
    make_event_order,
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


async def test_force_regenerates_a_report_already_on_event_orders():
    """A ready IT report carrying revenue_source='event_orders' is the
    exact state the idempotency guard skips. With force, the script must
    regenerate anyway: a fresh pair at max(version across languages)+1,
    both languages identical, predecessors superseded — with every other
    guard still applied (the run must end with all verifications green,
    i.e. exit code 0)."""
    from app.scripts.regenerate_reports_event_orders import run

    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        tenant_id = tenant.id
        try:
            event = await make_event(session, tenant_id, status=EventStatus.COMPLETED)
            await _complete_event(session, event)
            event_id = event.id
            bar = await make_bar(session, tenant_id, event_id)
            await make_event_order(
                session, tenant_id, event_id, bar_id=bar.id, fiscal_gross_cents=5000,
            )

            service = ReportService(session)
            it_v1 = await service.generate_on_demand(tenant_id, event_id, "it")
            en_v1 = await service.get_report_in_language(tenant_id, it_v1.id, "en")
            assert it_v1.data_json["revenue_source"] == "event_orders"
            assert en_v1.version == it_v1.version == 1
            it_v1_id, en_v1_id = it_v1.id, en_v1.id
            await session.commit()  # run() uses its own session

            # Guard intact without force: nothing new is created.
            rc = await run(tenant_id, event_id, execute=True, allow_parked=False,
                           force=False)
            assert rc == 0
            repo = ReportRepository(session)
            assert await repo.get_max_version_for_event(tenant_id, event_id) == 1

            # With force: regenerate anyway.
            rc = await run(tenant_id, event_id, execute=True, allow_parked=False,
                           force=True)
            assert rc == 0, "all inline verifications must still pass under force"

            # run() writes through its own session — read committed state
            # in a FRESH session so no cached instances mask the result.
            async with TestSessionLocal() as check:
                rows = await ReportRepository(check).list_for_event(tenant_id, event_id)
                by_key = {(r.language, r.version): r for r in rows}
                assert set(by_key) == {("it", 1), ("en", 1), ("it", 2), ("en", 2)}, (
                    "force must create exactly one new pair at "
                    "max(version across languages) + 1"
                )
                it_v2, en_v2 = by_key[("it", 2)], by_key[("en", 2)]
                assert it_v2.status == en_v2.status == "ready"
                assert (
                    it_v2.data_json["revenue_kpis"]["total_revenue"]
                    == en_v2.data_json["revenue_kpis"]["total_revenue"]
                    == "50.00"
                ), "the forced pair must carry identical totals in both languages"
                assert by_key[("it", 1)].id == it_v1_id
                assert by_key[("it", 1)].superseded_by == it_v2.id
                assert by_key[("en", 1)].id == en_v1_id
                assert by_key[("en", 1)].superseded_by == en_v2.id
        finally:
            await delete_tenant_cascade(session, tenant_id)
