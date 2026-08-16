"""Regression coverage: AlertsService.expire_event_alerts() exists but was
never called from anywhere — 0 of 391 alerts had ever expired in dev, and
alerts stayed "active" forever on already-COMPLETED events. end_event() now
calls it inline, in the same transaction as the completion itself.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.alerts.models import Alert
from app.modules.alerts.schemas import AlertCreate
from app.modules.alerts.service import AlertsService
from app.modules.events.models import EventStatus
from app.modules.events.service import EventService
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_bar,
    make_event,
    make_product,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def test_active_alert_is_expired_when_its_event_ends():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id, status=EventStatus.LIVE)
        event.started_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await session.flush()
        bar = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id)

        alert = await AlertsService(session).create_alert(
            tenant.id,
            AlertCreate(
                event_id=event.id, bar_id=bar.id, product_id=product.id,
                alert_type="depletion", severity="warning",
                audience="owner_and_manager",
                title="X running low at Y",
                owner_message="...",
            ),
        )
        await session.commit()
        tenant_id, event_id, alert_id = tenant.id, event.id, alert.id

    try:
        async with TestSessionLocal() as session:
            await EventService(db=session).end_event(tenant_id, event_id)

        async with TestSessionLocal() as session:
            row = (await session.execute(
                select(Alert).where(Alert.id == alert_id)
            )).scalar_one()
            assert row.expired_at is not None
            assert row.lifecycle_state == "expired"
            assert not row.is_active
    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)
            await session.commit()
