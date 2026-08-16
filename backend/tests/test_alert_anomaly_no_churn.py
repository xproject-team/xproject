"""Regression coverage for the anomaly-churn bug (2026-08).

DepletionEvaluator.evaluate() calls AlertsService.auto_resolve_missing()
with a still_active_keys set built ONLY from depletion conditions it just
checked. Before the fix, auto_resolve_missing scanned every active alert
regardless of type, so any active 'anomaly' alert (fired on a PREVIOUS
tick by a different detector) was auto-resolved on every single depletion
pass — even though depletion had no information about whether the
anomaly's condition still held. In production this hasn't fired yet (no
anomaly alert has existed at the same time as a depletion tick), but it
would churn the moment one does — confirmed in dev, where one ongoing
condition produced 123 separate rows.

The fix scopes auto_resolve_missing to the alert_type(s) the caller
actually evaluated, so DepletionEvaluator's pass never touches anomaly
rows.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.modules.alerts.engine import DepletionEvaluator
from app.modules.alerts.models import Alert
from app.modules.alerts.schemas import AlertCreate
from app.modules.alerts.service import AlertsService
from app.modules.stock_transactions.service import StockTransactionService
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_bar,
    make_event,
    make_product,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def _fake_compute_burn_rates(self, *, tenant_id, event_id, bar_id):
    """One burn-rate row that resolves to severity=None (current_qty and
    ttd both None) — just enough for DepletionEvaluator.evaluate() to get
    past its `if not burn_rows: return` early-exit and reach the
    auto-resolve call, without firing any new depletion alert itself."""
    return [{
        "product_id": None, "bar_id": None,
        "current_qty": None, "burn_rate_per_hour": None,
        "time_to_depletion_min": None, "window_label": "event_wide",
    }]


async def test_ongoing_anomaly_survives_two_depletion_ticks(monkeypatch):
    monkeypatch.setattr(
        StockTransactionService, "compute_burn_rates", _fake_compute_burn_rates,
    )

    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)
        bar = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id)

        # Seed one active anomaly alert, as if a demand-spike detector
        # fired it on a prior tick.
        anomaly = await AlertsService(session).create_alert(
            tenant.id,
            AlertCreate(
                event_id=event.id, bar_id=bar.id, product_id=product.id,
                alert_type="anomaly", severity="warning", audience="owner_only",
                title="Demand spike: X at Y",
                owner_message="Unusual consumption pattern detected.",
            ),
        )
        await session.commit()
        tenant_id, event_id, anomaly_id = tenant.id, event.id, anomaly.id

    try:
        # Tick 1
        async with TestSessionLocal() as session:
            await DepletionEvaluator(session).evaluate(tenant_id, event_id)
            await session.commit()

        # Tick 2
        async with TestSessionLocal() as session:
            await DepletionEvaluator(session).evaluate(tenant_id, event_id)
            await session.commit()

        async with TestSessionLocal() as session:
            rows = (await session.execute(
                select(Alert).where(
                    Alert.tenant_id == tenant_id,
                    Alert.event_id == event_id,
                    Alert.alert_type == "anomaly",
                )
            )).scalars().all()

            assert len(rows) == 1, (
                f"expected the anomaly alert to remain one row across two "
                f"depletion ticks, got {len(rows)}"
            )
            assert rows[0].id == anomaly_id
            assert rows[0].auto_resolved_at is None
            assert rows[0].is_active
    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)
            await session.commit()
