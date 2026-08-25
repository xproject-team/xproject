"""POS adapter factory — one construction seam for every app code path.

Staging runs a fake POS adapter serving provider-shaped payloads from
generated data; production keeps the real one. Selection is the
POS_ADAPTER setting: "slesh" (default — production behavior unchanged
with the variable absent) or "fake". All app construction sites route
through get_pos_adapter(); a mis-set Slesh variable can never reach the
fake because the factory constructs it with no Slesh settings at all.

Written FIRST, before the factory existed, per the failing-test rule.
"""
from __future__ import annotations

import pytest

from app.core.config import settings


def test_default_selects_slesh_adapter(monkeypatch):
    """POS_ADAPTER unset (field default 'slesh') → the real adapter,
    constructed exactly as production constructs it today."""
    from app.modules.pos.adapters.factory import get_pos_adapter
    from app.modules.pos.adapters.slesh import SleshAdapter

    monkeypatch.setattr(settings, "pos_adapter", "slesh")
    adapter = get_pos_adapter()
    assert isinstance(adapter, SleshAdapter)


def test_fake_selects_fake_adapter(monkeypatch):
    from app.modules.pos.adapters.factory import get_pos_adapter
    from app.modules.pos.adapters.fake import FakePOSAdapter

    monkeypatch.setattr(settings, "pos_adapter", "fake")
    adapter = get_pos_adapter()
    assert isinstance(adapter, FakePOSAdapter)


def test_unknown_value_raises_a_clear_error(monkeypatch):
    from app.modules.pos.adapters.factory import get_pos_adapter

    monkeypatch.setattr(settings, "pos_adapter", "sandbox")
    with pytest.raises(ValueError) as exc:
        get_pos_adapter()
    # The error must name the bad value and the accepted ones — this is
    # the message an operator sees after a typo in a service variable.
    assert "sandbox" in str(exc.value)
    assert "slesh" in str(exc.value) and "fake" in str(exc.value)


def test_selection_is_case_and_whitespace_tolerant(monkeypatch):
    """' Fake ' from a hand-typed dashboard variable must still select
    the fake — a silent fallback to the real adapter on sloppy input
    would point staging at the live provider."""
    from app.modules.pos.adapters.factory import get_pos_adapter
    from app.modules.pos.adapters.fake import FakePOSAdapter

    monkeypatch.setattr(settings, "pos_adapter", " Fake ")
    assert isinstance(get_pos_adapter(), FakePOSAdapter)


def test_dead_posservice_is_gone():
    """pos/service.py held a stub POSService constructing SleshAdapter()
    with no credentials; nothing imported it (verified repo-wide). It is
    deleted rather than routed through the factory — dead code carrying
    an adapter construction is exactly what the factory must not leave
    behind."""
    with pytest.raises(ModuleNotFoundError):
        import app.modules.pos.service  # noqa: F401


# ─── Cron guards: "is a POS adapter configured and usable?" ──────────────────
#
# The old guards checked settings.slesh_api_token directly — correct for
# production, but it made a token-less staging (POS_ADAPTER=fake) skip
# the entire ingestion path, which is the one thing staging exists to
# rehearse. The guard becomes pos_adapter_configured().


def test_configured_truth_table(monkeypatch):
    from app.modules.pos.adapters.factory import pos_adapter_configured

    # Production regression guard: default selection, no token → NOT usable.
    monkeypatch.setattr(settings, "pos_adapter", "slesh")
    monkeypatch.setattr(settings, "slesh_api_token", "")
    assert pos_adapter_configured() is False

    # Production happy path: default selection, token present → usable.
    monkeypatch.setattr(settings, "slesh_api_token", "tok")
    assert pos_adapter_configured() is True

    # Staging: fake needs no credentials.
    monkeypatch.setattr(settings, "pos_adapter", "fake")
    monkeypatch.setattr(settings, "slesh_api_token", "")
    assert pos_adapter_configured() is True

    # A typo'd selection must not report usable (crons skip; explicit
    # construction raises the loud ValueError).
    monkeypatch.setattr(settings, "pos_adapter", "sandbox")
    assert pos_adapter_configured() is False


import pytest as _pytest


@_pytest.mark.asyncio
async def test_poll_cron_skips_exactly_as_today_without_adapter(monkeypatch):
    """POS_ADAPTER unset + no token → the cron returns the exact skip
    payload staging logs show every minute today. This is the production
    regression guard: nothing about the no-adapter path may change."""
    from app.workers.tasks import cron_poll_slesh_for_all_live_events

    monkeypatch.setattr(settings, "pos_adapter", "slesh")
    monkeypatch.setattr(settings, "slesh_api_token", "")
    # ctx is never touched on the skip path — an empty dict proves it.
    result = await cron_poll_slesh_for_all_live_events({})
    assert result == {"status": "skipped", "reason": "no_token", "enqueued": 0}


@_pytest.mark.asyncio
async def test_bars_cron_skips_exactly_as_today_without_adapter(monkeypatch):
    from app.workers.tasks import cron_sync_bars_from_slesh

    monkeypatch.setattr(settings, "pos_adapter", "slesh")
    monkeypatch.setattr(settings, "slesh_api_token", "")
    result = await cron_sync_bars_from_slesh({})
    assert result == {"status": "skipped", "reason": "no_token"}


@_pytest.mark.asyncio
async def test_poll_cron_runs_with_fake_adapter_and_no_token(monkeypatch):
    """POS_ADAPTER=fake, no token → polling MUST run: live events are
    enumerated and enqueued. Uses a stub arq pool so nothing reaches a
    real queue, and its own live event so the assertion does not depend
    on ambient DB state."""
    from datetime import datetime, timezone

    from sqlalchemy import update

    from app.modules.events.models import Event, EventStatus
    from app.workers.tasks import cron_poll_slesh_for_all_live_events
    from tests.fixtures.alerts.factories import delete_tenant_cascade, make_event, make_tenant
    from tests.fixtures.alerts.session import TestSessionLocal

    monkeypatch.setattr(settings, "pos_adapter", "fake")
    monkeypatch.setattr(settings, "slesh_api_token", "")

    class StubRedis:
        def __init__(self): self.enqueued = []
        async def enqueue_job(self, name, *args, _job_id=None, **kw):
            self.enqueued.append((name, args, _job_id))
            return object()

    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.LIVE)
            await session.execute(update(Event).where(Event.id == event.id).values(
                started_at=datetime.now(timezone.utc)))
            await session.commit()

            stub = StubRedis()
            result = await cron_poll_slesh_for_all_live_events({"redis": stub})

            assert result["status"] == "ok"
            assert any(str(event.id) in (jid or "") for _n, _a, jid in stub.enqueued), (
                "the live event must be enqueued for polling when the fake "
                "adapter is configured, token or no token"
            )
        finally:
            await delete_tenant_cascade(session, tenant.id)


@_pytest.mark.asyncio
async def test_bars_cron_runs_with_fake_adapter_and_no_token(monkeypatch):
    """POS_ADAPTER=fake, no token → shop sync MUST run, and the adapter
    handed to sync_shops must be the fake."""
    from datetime import datetime, timezone

    from sqlalchemy import update

    import app.modules.pos.sync_service as sync_service
    from app.modules.events.models import Event, EventStatus
    from app.modules.pos.adapters.fake import FakePOSAdapter
    from app.workers.tasks import cron_sync_bars_from_slesh
    from tests.fixtures.alerts.factories import delete_tenant_cascade, make_event, make_tenant
    from tests.fixtures.alerts.session import TestSessionLocal

    monkeypatch.setattr(settings, "pos_adapter", "fake")
    monkeypatch.setattr(settings, "slesh_api_token", "")

    seen = []

    from types import SimpleNamespace

    async def _recording_sync_shops(*, db, tenant_id, event_id, adapter, **kw):
        seen.append((event_id, adapter))
        return SimpleNamespace(created=0, updated=0, skipped=0, deactivated=0)

    monkeypatch.setattr(sync_service, "sync_shops", _recording_sync_shops)

    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.LIVE)
            await session.execute(update(Event).where(Event.id == event.id).values(
                started_at=datetime.now(timezone.utc)))
            await session.commit()

            result = await cron_sync_bars_from_slesh({})

            assert result["status"] != "skipped"
            ours = [a for eid, a in seen if eid == event.id]
            assert ours, "our live event must be shop-synced under the fake adapter"
            assert isinstance(ours[0], FakePOSAdapter)
        finally:
            await delete_tenant_cascade(session, tenant.id)
