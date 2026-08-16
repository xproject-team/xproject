"""Regression coverage for PredictionRepository.list_historical_completed_events'
is_training_eligible filter.

HeuristicPredictor (the Predictions page) computes per-guest averages from
this query's output. nowcast/retrain.py already filters is_training_eligible
on the exact same contamination guard (migrations aa3 + aa4 — the dev DB has
17+ simulation/test/seed fixture events backfilled false for this reason);
this query didn't, so a simulation event could silently scale a "per-guest
average" that was never a real night.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.events.models import EventStatus
from app.modules.predictions.repository import PredictionRepository
from tests.fixtures.alerts.factories import delete_tenant_cascade, make_event, make_tenant
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def _make_completed_event(session, tenant_id, *, is_training_eligible: bool):
    ev = await make_event(session, tenant_id, status=EventStatus.COMPLETED)
    now = datetime.now(timezone.utc)
    ev.started_at = now - timedelta(hours=6)
    ev.ended_at = now - timedelta(hours=1)
    ev.is_training_eligible = is_training_eligible
    await session.flush()
    return ev


async def test_ineligible_event_excluded_from_historical_basis():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            eligible = await _make_completed_event(session, tenant.id, is_training_eligible=True)
            ineligible = await _make_completed_event(session, tenant.id, is_training_eligible=False)
            await session.flush()

            rows = await PredictionRepository(session).list_historical_completed_events(tenant.id)
            ids = {e.id for e in rows}

            assert eligible.id in ids
            assert ineligible.id not in ids
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()
