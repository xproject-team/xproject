"""Tests for EventService.start_event's stale-live-event auto-completion.

Regression coverage for the bug where a stale LIVE event (ended_at already
past) blocking another event from starting was force-completed via a bare
repo.update() — bypassing end_event() entirely, so none of its three
post-event background jobs (nowcast retrain, demand retrain, customer-
features population) ever fired for it. That event's customer_sessions
stayed permanently empty with no signal anything had differed from a normal
completion.

Uses the SAVEPOINT db_session fixture (like test_event_auto_transitions.py)
so xproject_dev is never mutated, plus an isolated nested-session factory
patched into app.modules.events.service.AsyncSessionLocal — the same
"genuinely separate session, same underlying connection" pattern F-02 needed
to be exercised meaningfully for the cron.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.events.service as events_service_module
from app.modules.events.models import EventStatus
from app.modules.events.service import EventService
from tests.fixtures.alerts.factories import make_event, make_tenant

pytestmark = pytest.mark.asyncio


@pytest.fixture
def patched_events_service_session_factory(db_session: AsyncSession, monkeypatch):
    """Like test_event_auto_transitions.py's patched_isolated_session_factory,
    but targets app.modules.events.service.AsyncSessionLocal — the factory
    _auto_end_stale_live() actually calls. Each call returns a GENUINELY
    separate AsyncSession bound to the same underlying connection as
    db_session (so it rolls back with everything else at test teardown),
    but with its own identity map, so its rollback/commit can't expire ORM
    objects db_session is still holding onto.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    NestedSession = async_sessionmaker(
        bind=db_session._test_connection, expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    opened: list[AsyncSession] = []

    class _FreshSessionWrapper:
        async def __aenter__(self):
            session = NestedSession()
            opened.append(session)
            return session
        async def __aexit__(self, *args):
            await opened[-1].close()
            return None

    monkeypatch.setattr(
        events_service_module, "AsyncSessionLocal",
        lambda: _FreshSessionWrapper(),
    )
    return db_session


async def test_stale_live_conflict_routes_through_end_event_and_fires_jobs(
    db_session: AsyncSession, patched_events_service_session_factory, monkeypatch,
):
    """Starting event B while event A is stale-LIVE must complete A via the
    same path (and same background jobs) end_event() normally triggers —
    not a bare status flip."""
    calls: dict[str, list] = {"nowcast": [], "demand": [], "customer_features": []}

    async def _fake_nowcast(tenant_id):
        calls["nowcast"].append(tenant_id)

    async def _fake_demand(tenant_id, event_id):
        calls["demand"].append((tenant_id, event_id))

    async def _fake_customer_features(tenant_id, event_id):
        calls["customer_features"].append((tenant_id, event_id))

    monkeypatch.setattr(events_service_module, "_enqueue_nowcast_retrain", _fake_nowcast)
    monkeypatch.setattr(events_service_module, "_enqueue_demand_retrain", _fake_demand)
    monkeypatch.setattr(
        events_service_module, "_enqueue_customer_features_population",
        _fake_customer_features,
    )

    tenant = await make_tenant(db_session)
    stale = await make_event(db_session, tenant.id, status=EventStatus.LIVE)
    stale.ended_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await db_session.flush()
    incoming = await make_event(db_session, tenant.id, status=EventStatus.ACTIVE)

    service = EventService(db=db_session)
    result = await service.start_event(tenant.id, incoming.id)

    assert result.status == EventStatus.LIVE

    await db_session.refresh(stale)
    assert stale.status == EventStatus.COMPLETED

    assert calls["nowcast"] == [tenant.id]
    assert calls["demand"] == [(tenant.id, stale.id)]
    assert calls["customer_features"] == [(tenant.id, stale.id)]


async def test_stale_live_auto_end_failure_does_not_block_new_event_start(
    db_session: AsyncSession, patched_events_service_session_factory, monkeypatch,
):
    """A failure in A's post-completion background-job phase (the part
    end_event() runs AFTER its own status commit already succeeded — e.g.
    a bug in the enqueue machinery, despite each enqueue helper normally
    being self-contained) must not prevent event B from starting.

    Note: A's own STATUS TRANSITION failing outright is a different,
    unavoidable case — the one-live-per-tenant DB constraint means B
    genuinely cannot go LIVE while A's row is still LIVE, no matter how
    A's completion attempt is wrapped. That's correct: only a failure in
    A's completion *work* (not the completion itself) should be
    swallowed, matching _enqueue_nowcast_retrain/_enqueue_demand_retrain/
    _enqueue_customer_features_population, which already never raise by
    design (see their own docstrings) — this test defends that contract
    even if one of them regressed."""
    async def _boom(tenant_id):
        raise RuntimeError("simulated bug in enqueue machinery")

    monkeypatch.setattr(events_service_module, "_enqueue_nowcast_retrain", _boom)

    tenant = await make_tenant(db_session)
    stale = await make_event(db_session, tenant.id, status=EventStatus.LIVE)
    stale.ended_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await db_session.flush()
    incoming = await make_event(db_session, tenant.id, status=EventStatus.ACTIVE)

    service = EventService(db=db_session)
    result = await service.start_event(tenant.id, incoming.id)

    assert result.status == EventStatus.LIVE
    assert result.id == incoming.id

    # A's own status transition must have still landed despite the later
    # enqueue-phase failure — the commit happens before the enqueue calls.
    await db_session.refresh(stale)
    assert stale.status == EventStatus.COMPLETED
