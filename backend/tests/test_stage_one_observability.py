"""Stage one of the job-status-semantics remediation: make outcomes
VISIBLE without changing behaviour (docs/job-status-semantics.md).

No new failure states, no changed return values that anything acts on:
end_event() keeps returning the Event (both callers — the router and
the auto-end cron — depend on that); the three enqueue helpers now
RETURN their outcome instead of discarding it, and end_event logs one
structured dispatch line. The four dangerous jobs gain fact fields —
the inputs to a verdict, not a verdict.

Written FIRST, per the failing-test rule.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.modules.events.models import Event, EventStatus
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_event,
    make_event_order,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


class _StubPool:
    """Stands in for the arq redis pool. behaviour: 'ok' → job handle,
    'dedup' → None (arq's _job_id-collision signal), 'raise' → error."""

    def __init__(self, behaviour: str):
        self.behaviour = behaviour

    async def enqueue_job(self, *a, **kw):
        if self.behaviour == "raise":
            raise ConnectionError("redis unreachable (stub)")
        return None if self.behaviour == "dedup" else object()

    async def close(self):
        return None


def _patch_pool(monkeypatch, behaviour: str):
    import arq.connections as arq_conn

    async def _fake_create_pool(*a, **kw):
        return _StubPool(behaviour)

    monkeypatch.setattr(arq_conn, "create_pool", _fake_create_pool)


# ─── end_event: per-job dispatch outcomes ────────────────────────────────────

async def test_enqueue_helpers_return_their_outcome(monkeypatch):
    from uuid import uuid4

    from app.modules.events.service import (
        _enqueue_customer_features_population,
        _enqueue_demand_retrain,
        _enqueue_nowcast_retrain,
    )

    tid, eid = uuid4(), uuid4()

    _patch_pool(monkeypatch, "ok")
    for coro, job in (
        (_enqueue_nowcast_retrain(tid), "retrain_predictor"),
        (_enqueue_demand_retrain(tid, eid), "retrain_demand_predictor"),
        (_enqueue_customer_features_population(tid, eid), "populate_customer_features"),
    ):
        outcome = await coro
        assert outcome["job"] == job
        assert outcome["enqueued"] is True

    _patch_pool(monkeypatch, "dedup")
    outcome = await _enqueue_nowcast_retrain(tid)
    assert outcome["enqueued"] is False
    assert "dedup" in outcome["reason"].lower()

    _patch_pool(monkeypatch, "raise")
    outcome = await _enqueue_demand_retrain(tid, eid)
    assert outcome["enqueued"] is False
    assert "ConnectionError" in outcome["reason"]


async def test_end_event_logs_one_dispatch_line_and_still_returns_the_event(
    monkeypatch, caplog,
):
    from app.modules.events.service import EventService

    _patch_pool(monkeypatch, "ok")
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.LIVE)
            await session.execute(update(Event).where(Event.id == event.id).values(
                started_at=datetime.now(timezone.utc) - timedelta(hours=2),
            ))
            await session.commit()

            with caplog.at_level(logging.INFO, logger="app.modules.events.service"):
                returned = await EventService(session).end_event(tenant.id, event.id)

            # Contract unchanged: callers still receive the Event.
            assert returned.id == event.id
            assert returned.status == EventStatus.COMPLETED

            dispatch_lines = [
                r.message for r in caplog.records
                if "post-event dispatch" in r.message
            ]
            assert len(dispatch_lines) == 1, caplog.text
            line = dispatch_lines[0]
            for job in ("retrain_predictor", "retrain_demand_predictor",
                        "populate_customer_features"):
                assert f"{job}=enqueued" in line, line
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_end_event_dispatch_line_names_the_failure(monkeypatch, caplog):
    from app.modules.events.service import EventService

    _patch_pool(monkeypatch, "raise")
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.LIVE)
            await session.execute(update(Event).where(Event.id == event.id).values(
                started_at=datetime.now(timezone.utc) - timedelta(hours=2),
            ))
            await session.commit()

            with caplog.at_level(logging.INFO, logger="app.modules.events.service"):
                returned = await EventService(session).end_event(tenant.id, event.id)

            # Behaviour unchanged: the event still completes.
            assert returned.status == EventStatus.COMPLETED
            line = next(r.message for r in caplog.records
                        if "post-event dispatch" in r.message)
            assert "NOT-enqueued" in line and "ConnectionError" in line, line
        finally:
            await delete_tenant_cascade(session, tenant.id)


# ─── The four dangerous jobs: fact fields ────────────────────────────────────

async def test_poll_task_reports_window_and_skip_reasons(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    import app.modules.pos.slesh_poller as sp
    from app.modules.pos.poll_state import PollWindow
    from app.workers.tasks import poll_slesh_for_event

    since = datetime(2026, 9, 5, 18, 0, tzinfo=timezone.utc)
    fake_result = SimpleNamespace(
        status="ok", orders_seen=9, orders_ingested=0,
        lines_ingested=0, lines_replayed=0, lines_skipped=12, lines_errors=9,
        error_msg="",
        window=PollWindow(since_ts=since, until_ts=since + timedelta(seconds=90)),
        per_order_results=[
            SimpleNamespace(skip_reasons=[
                "order parked — unmapped shop_id abc",
                "line 1: no product matched xyz",
            ]),
            SimpleNamespace(skip_reasons=["line 2: marked refunded"]),
        ],
    )

    async def _fake_poll(**kw):
        return fake_result

    monkeypatch.setattr(sp, "poll_slesh_orders", _fake_poll)
    out = await poll_slesh_for_event({}, str(uuid4()), str(uuid4()))

    assert out["status"] == "ok"
    assert out["window_since"] == since.isoformat()
    assert out["window_until"] == (since + timedelta(seconds=90)).isoformat()
    reasons = out["lines_skipped_reasons"]
    assert reasons["parked_unmapped_shop"] == 1
    assert reasons["no_product_match"] == 1
    assert reasons["refunded_line"] == 1


async def test_populate_features_task_reports_the_inputs_to_a_verdict(monkeypatch):
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            await make_event_order(session, tenant.id, event.id, fiscal_gross_cents=1000)
            await make_event_order(session, tenant.id, event.id, fiscal_gross_cents=2000)
            await make_event_order(  # fully refunded — not confirmed
                session, tenant.id, event.id, fiscal_gross_cents=0,
                confirmed_line_count=0, refunded_line_count=1,
            )
            await session.commit()

            from app.workers.tasks import populate_customer_features

            out = await populate_customer_features({}, str(tenant.id), str(event.id))

            # The facts: what the event held vs what the builder found.
            # (No user identities on these orders → 0 sessions is the
            # truthful outcome; the fields make that judgeable.)
            assert out["confirmed_orders_seen"] == 2
            assert out["identified_orders_seen"] == 0
            assert out["sessions_created"] == 0
            assert "zero_line_orders" in out
            assert out["status"] == "ok"  # stage one: unchanged semantics
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_generate_report_task_reports_per_language_db_truth():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
            now = datetime.now(timezone.utc)
            await session.execute(update(Event).where(Event.id == event.id).values(
                started_at=now - timedelta(hours=10), ended_at=now - timedelta(hours=2),
            ))
            await make_event_order(session, tenant.id, event.id, fiscal_gross_cents=5000)
            await session.commit()

            from app.workers.tasks import generate_report

            out = await generate_report({}, str(event.id))

            assert out["status"] == "ok"
            # Facts queried from the database, not from the swallowing
            # batch method: per-language latest status.
            assert out["languages"] == {"it": "ready", "en": "ready"}
            assert out["reports_generated"] == 2
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_run_predictions_stub_says_it_is_a_stub():
    from uuid import uuid4

    from app.workers.tasks import run_predictions

    out = await run_predictions({}, str(uuid4()))
    assert out["status"] == "ok"
    assert out["stub"] is True
    assert "not implemented" in out["note"].lower()
