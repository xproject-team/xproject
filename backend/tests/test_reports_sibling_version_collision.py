"""FAILING-FIRST reproduction of the sibling version collision found in
Round-4 production pre-flight (2026-08-22). DO NOT "fix" this test —
it encodes the correct behavior; the service must change to satisfy it.

Production shape on Jul-5/Jul-19/Aug-2 (tenant 25ef916c…):
    IT v1  ready, NOT superseded, old-method total
    EN v1  ready, superseded → EN v2
    EN v2  ready, NOT superseded, old-method total
Version sequences diverged per language (latest IT = v1, latest EN = v2).
How they diverged is not established — more than one code path can
produce this shape; the fix does not depend on which one did.

The bug: regenerate(IT v1) allocates version per LANGUAGE
(get_latest_for_event(…, 'it') → v1 → new IT v2). The language-sibling
lookup then matches on (version, language) with no content or status
check (service.py:115-119) — and EN v2 ALREADY EXISTS holding the
old-method number. The stale row is returned; no sibling is derived.
Outcome: IT v2 = new total, EN v2 = old total, both "current".

Correct behavior (asserted here): a regenerated report must take a
version number that is free in EVERY language, so its sibling slot is
guaranteed empty and the derived sibling carries identical numbers;
the stale old-method EN row must end up superseded.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.modules.events.models import Event, EventStatus
from app.modules.reports.models import Report
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


def _old_report(tenant_id, event_id, *, language, version, superseded_by=None) -> Report:
    """Pre-migration snapshot: old-method total, no revenue_source key."""
    return Report(
        tenant_id=tenant_id, event_id=event_id, language=language,
        version=version, status="ready", superseded_by=superseded_by,
        data_json={"revenue_kpis": {"total_revenue": "39618.00"}},
        generated_at=datetime.now(timezone.utc),
    )


async def test_regenerate_with_drifted_language_versions_derives_fresh_sibling():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await _complete_event(session, event)
            bar = await make_bar(session, tenant.id, event.id)
            # New-definition truth: €50,760.00
            await make_event_order(session, tenant.id, event.id, bar_id=bar.id,
                                   fiscal_gross_cents=5076000)

            # Production shape: IT v1 current; EN v1 → EN v2; EN v2 current (old numbers).
            it_v1 = _old_report(tenant.id, event.id, language="it", version=1)
            en_v2 = _old_report(tenant.id, event.id, language="en", version=2)
            session.add_all([it_v1, en_v2])
            await session.flush()
            en_v1 = _old_report(tenant.id, event.id, language="en", version=1,
                                superseded_by=en_v2.id)
            session.add(en_v1)
            await session.flush()

            service = ReportService(session)
            new_it = await service.regenerate(tenant.id, it_v1.id, generated_by=None)

            assert new_it.status == "ready"
            # Version must clear EVERY language's sequence (EN is at v2),
            # or the sibling lookup collides with the stale EN v2.
            assert new_it.version == 3, (
                f"regenerated IT landed on v{new_it.version}; EN already holds "
                "v2 with old-method numbers — the sibling slot is occupied"
            )

            sibling = await service.get_report_in_language(tenant.id, new_it.id, "en")
            assert sibling.id != en_v2.id, (
                "sibling lookup returned the STALE pre-migration EN row "
                "instead of deriving from the new snapshot"
            )
            assert sibling.status == "ready"
            assert (
                sibling.data_json["revenue_kpis"]["total_revenue"]
                == new_it.data_json["revenue_kpis"]["total_revenue"]
                == "50760.00"
            ), "language pair must carry identical, new-definition numbers"
        finally:
            await delete_tenant_cascade(session, tenant.id)
