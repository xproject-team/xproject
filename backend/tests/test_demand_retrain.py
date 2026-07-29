"""Integration tests for the demand model's retrain/persistence path —
the first real consumer of model_artifacts (see retrain.py's module
docstring). Writes to tmp_path, never the real
predictions/artifacts/demand/ directory, matching
test_nowcast_retrain.py's isolation discipline.

Uses the REAL historical parquet (app/modules/predictions/nowcast/data/
training_transactions.parquet) as the fixed reference data — it's
static, checked-in data, not something a test needs to fake; only the
live-DB side (COMPLETED events' customer_purchases) is fixtured here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select

from app.modules.events.models import Event, EventStatus
from app.modules.predictions.demand.retrain import (
    MODEL_NAME,
    _JUL5_SHAPE_ONLY_EVENT_ID,
    _looks_like_uuid,
    retrain_demand_model,
)
from app.modules.predictions.models import ModelArtifact
from app.modules.products.models import ProductType
from app.modules.stock_transactions.models import TransactionSource
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_bar,
    make_event,
    make_product,
    make_stock_transaction,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal


def test_looks_like_uuid():
    assert _looks_like_uuid(str(UUID(int=0))) is True
    assert _looks_like_uuid("sundance_2024-06-16") is False
    assert _looks_like_uuid(None) is False


def test_jul5_shape_only_event_id_is_stable():
    """A basic guardrail against silently editing away the Jul-5
    shape-only special case — if this ever needs to change, it should
    be a deliberate, reviewed diff, not an accidental one."""
    assert _JUL5_SHAPE_ONLY_EVENT_ID == UUID("0888f4b7-7030-426b-815c-938e6ca447a6")


async def _seed_completed_event_with_purchases(session, tenant, *, n_orders: int = 3):
    from app.modules.customer_analytics.models import CustomerPurchase

    event = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
    bar = await make_bar(session, tenant.id, event.id)
    product = await make_product(session, tenant.id, product_type=ProductType.DRINK)
    for i in range(n_orders):
        session.add(CustomerPurchase(
            tenant_id=tenant.id, event_id=event.id, customer_key=f"cust-{i}",
            slesh_order_id=f"o-{i}", product_id=product.id, product_name="Gin Tonic",
            category="cocktail", bar_id=bar.id, qty=Decimal("1"), price_cents=1000,
            is_deposit=False, ordered_at=datetime(2026, 8, 2, 12 + i, tzinfo=timezone.utc),
        ))
    await session.commit()
    return event


@pytest.mark.asyncio
async def test_retrain_writes_active_model_artifact(tmp_path):
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await _seed_completed_event_with_purchases(session, tenant)

        result = await retrain_demand_model(
            session, tenant.id, triggered_by="test", triggered_by_event_id=event.id,
            artifacts_dir=tmp_path,
        )
        assert result["status"] == "ok"
        assert result["retrained"] is True
        assert result["version"] == 1
        # 9 historical + 1 current event
        assert result["n_training_events"] == 10

        artifact = (await session.execute(
            select(ModelArtifact).where(
                ModelArtifact.tenant_id == tenant.id, ModelArtifact.model_name == MODEL_NAME,
            )
        )).scalar_one()
        assert artifact.is_active is True
        assert artifact.version == 1
        assert artifact.triggered_by == "test"
        assert artifact.triggered_by_event_id == event.id
        assert Path(artifact.file_path).exists()
        assert artifact.file_size_bytes > 0
        assert len(artifact.file_sha256) == 64  # sha256 hex digest length
        assert event.id in artifact.training_event_ids

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_retrain_second_run_versions_up_and_deactivates_previous(tmp_path):
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event1 = await _seed_completed_event_with_purchases(session, tenant)

        first = await retrain_demand_model(
            session, tenant.id, triggered_by="test", artifacts_dir=tmp_path,
        )
        assert first["version"] == 1

        event2 = await _seed_completed_event_with_purchases(session, tenant)
        second = await retrain_demand_model(
            session, tenant.id, triggered_by="test", artifacts_dir=tmp_path,
        )
        assert second["version"] == 2

        artifacts = (await session.execute(
            select(ModelArtifact).where(
                ModelArtifact.tenant_id == tenant.id, ModelArtifact.model_name == MODEL_NAME,
            ).order_by(ModelArtifact.version)
        )).scalars().all()
        assert len(artifacts) == 2
        assert artifacts[0].version == 1 and artifacts[0].is_active is False
        assert artifacts[0].deprecated_at is not None
        assert artifacts[1].version == 2 and artifacts[1].is_active is True

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_retrain_excludes_non_training_eligible_events(tmp_path):
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        eligible = await _seed_completed_event_with_purchases(session, tenant)

        ineligible = await make_event(session, tenant.id, status=EventStatus.COMPLETED)
        ineligible.is_training_eligible = False
        bar = await make_bar(session, tenant.id, ineligible.id)
        product = await make_product(session, tenant.id, product_type=ProductType.DRINK)
        from app.modules.customer_analytics.models import CustomerPurchase
        session.add(CustomerPurchase(
            tenant_id=tenant.id, event_id=ineligible.id, customer_key="cust-x",
            slesh_order_id="o-x", product_id=product.id, product_name="Gin Tonic",
            category="cocktail", bar_id=bar.id, qty=Decimal("1"), price_cents=1000,
            is_deposit=False, ordered_at=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
        ))
        await session.commit()

        result = await retrain_demand_model(
            session, tenant.id, triggered_by="test", artifacts_dir=tmp_path,
        )
        # 9 historical + only the eligible current event, not the ineligible one
        assert result["n_training_events"] == 10

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_retrain_excludes_jul5_from_per_line_path_even_if_eligible(tmp_path):
    """Regression test: a real retrain against production data showed
    n_training_events jump 11 -> 12 because Jul-5's is_training_eligible
    flag was (unexpectedly) true, letting it re-enter through the
    regular per-line query despite its per-bar coverage gaps -- exactly
    what its shape-only-only treatment exists to prevent. The exclusion
    must hold by hard-coded event id, independent of the eligibility
    flag's value."""
    from app.modules.customer_analytics.models import CustomerPurchase
    from app.modules.predictions.demand.retrain import _JUL5_SHAPE_ONLY_EVENT_ID

    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        eligible = await _seed_completed_event_with_purchases(session, tenant)

        jul5_lookalike = Event(
            id=_JUL5_SHAPE_ONLY_EVENT_ID, tenant_id=tenant.id, venue_id=eligible.venue_id,
            name="Sundence Jul-5", status=EventStatus.COMPLETED, is_training_eligible=True,
            expected_guest_count=100, scheduled_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            scheduled_end_at=datetime(2026, 7, 5, 23, tzinfo=timezone.utc), version=1,
        )
        session.add(jul5_lookalike)
        await session.flush()
        bar = await make_bar(session, tenant.id, jul5_lookalike.id)
        product = await make_product(session, tenant.id, product_type=ProductType.DRINK)
        session.add(CustomerPurchase(
            tenant_id=tenant.id, event_id=jul5_lookalike.id, customer_key="cust-jul5",
            slesh_order_id="o-jul5", product_id=product.id, product_name="Gin Tonic",
            category="cocktail", bar_id=bar.id, qty=Decimal("1"), price_cents=1000,
            is_deposit=False, ordered_at=datetime(2026, 7, 5, 12, tzinfo=timezone.utc),
        ))
        await session.commit()

        result = await retrain_demand_model(
            session, tenant.id, triggered_by="test", artifacts_dir=tmp_path,
        )
        # 9 historical + only the non-Jul5 eligible event -- Jul-5 excluded
        # from the per-line grid regardless of its eligibility flag.
        assert result["n_training_events"] == 10

        await delete_tenant_cascade(session, tenant.id)
