"""Regression coverage for AlertsService.resolve() (migration ag1).

Before this, the only lifecycle action available on an alert was
acknowledge — there was no way to mark one resolved when the underlying
condition was fixed OUTSIDE the platform (the 2 August unmapped-shop case:
the Slesh shop mapping was corrected via direct DB work, so nobody ever
called pending_shop_mappings_service.resolve(), and nobody had clicked
Acknowledge either — the alert would otherwise stay open indefinitely).

resolve() is distinct from acknowledge(): it sets resolved_at/
resolved_by_user_id (new columns, migration ag1), never touches
acknowledged_at, and works whether or not the alert was ever acknowledged.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.alerts.models import Alert
from app.modules.alerts.schemas import AlertCreate
from app.modules.alerts.service import (
    AlertAlreadyResolvedError,
    AlertsService,
    StaleAlertVersionError,
)
from app.modules.auth.models import User, UserRole
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_bar,
    make_event,
    make_product,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def _make_owner(session, tenant_id) -> User:
    u = User(
        tenant_id=tenant_id,
        email=f"owner-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="Test Owner",
        role=UserRole.OWNER,
        is_active=True,
    )
    session.add(u)
    await session.flush()
    return u


async def _make_alert(session, tenant, event, bar, product) -> Alert:
    return await AlertsService(session).create_alert(
        tenant.id,
        AlertCreate(
            event_id=event.id, bar_id=bar.id, product_id=product.id,
            alert_type="system", severity="warning",
            audience="owner_only",
            title="Unmapped Slesh shop",
            owner_message="An order arrived from a shop with no bar mapping.",
        ),
    )


async def test_resolve_sets_resolved_fields_without_touching_acknowledge():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)
        bar = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id)
        owner = await _make_owner(session, tenant.id)
        alert = await _make_alert(session, tenant, event, bar, product)
        await session.commit()
        tenant_id, alert_id, owner_id = tenant.id, alert.id, owner.id

    try:
        async with TestSessionLocal() as session:
            result = await AlertsService(session).resolve(
                tenant_id=tenant_id, alert_id=alert_id,
                user_id=owner_id, expected_version=1,
            )
            await session.commit()

        assert result.resolved_by_user_id == owner_id
        assert result.lifecycle_state == "resolved"

        async with TestSessionLocal() as session:
            row = (await session.execute(
                select(Alert).where(Alert.id == alert_id)
            )).scalar_one()
            assert row.resolved_at is not None
            assert row.resolved_by_user_id == owner_id
            # Distinct from acknowledge — resolve never touches these.
            assert row.acknowledged_at is None
            assert row.acknowledged_by_user_id is None
            assert row.auto_resolved_at is None
            assert not row.is_active
            assert row.lifecycle_state == "resolved"
    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)
            await session.commit()


async def test_resolve_works_without_prior_acknowledge_and_disappears_from_active_list():
    """The exact 2 August scenario: nobody acknowledged it, the underlying
    condition was just fixed. Resolve must still work, and the alert must
    stop showing up as active afterward."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)
        bar = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id)
        owner = await _make_owner(session, tenant.id)
        alert = await _make_alert(session, tenant, event, bar, product)
        await session.commit()
        tenant_id, event_id, alert_id, owner_id = (
            tenant.id, event.id, alert.id, owner.id,
        )

    try:
        async with TestSessionLocal() as session:
            counts_before = await AlertsService(session).count_active(tenant_id, event_id)
            assert counts_before["total"] == 1

            await AlertsService(session).resolve(
                tenant_id=tenant_id, alert_id=alert_id,
                user_id=owner_id, expected_version=1,
            )
            await session.commit()

        async with TestSessionLocal() as session:
            counts_after = await AlertsService(session).count_active(tenant_id, event_id)
            assert counts_after["total"] == 0
    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)
            await session.commit()


async def test_resolve_twice_raises_already_resolved():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)
        bar = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id)
        owner = await _make_owner(session, tenant.id)
        alert = await _make_alert(session, tenant, event, bar, product)
        await session.commit()
        tenant_id, alert_id, owner_id = tenant.id, alert.id, owner.id

    try:
        async with TestSessionLocal() as session:
            await AlertsService(session).resolve(
                tenant_id=tenant_id, alert_id=alert_id,
                user_id=owner_id, expected_version=1,
            )
            await session.commit()

        async with TestSessionLocal() as session:
            with pytest.raises(AlertAlreadyResolvedError):
                await AlertsService(session).resolve(
                    tenant_id=tenant_id, alert_id=alert_id,
                    user_id=owner_id, expected_version=2,
                )
    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)
            await session.commit()


async def test_resolve_stale_version_raises():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)
        bar = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id)
        owner = await _make_owner(session, tenant.id)
        alert = await _make_alert(session, tenant, event, bar, product)
        await session.commit()
        tenant_id, alert_id, owner_id = tenant.id, alert.id, owner.id

    try:
        async with TestSessionLocal() as session:
            with pytest.raises(StaleAlertVersionError):
                await AlertsService(session).resolve(
                    tenant_id=tenant_id, alert_id=alert_id,
                    user_id=owner_id, expected_version=999,
                )
    finally:
        async with TestSessionLocal() as session:
            await delete_tenant_cascade(session, tenant_id)
            await session.commit()
