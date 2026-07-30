"""Tests for demand/loader.py — the read path model_artifacts never had
before this: get_active_demand_predictor unpickles the active artifact
and caches it per-tenant, invalidating only when the active row changes.
"""
from __future__ import annotations

import pytest

from app.modules.predictions.demand import loader as loader_module
from app.modules.predictions.demand.loader import get_active_demand_predictor
from app.modules.predictions.demand.retrain import retrain_demand_model
from tests.fixtures.alerts.factories import delete_tenant_cascade, make_tenant
from tests.fixtures.alerts.session import TestSessionLocal


@pytest.fixture(autouse=True)
def _clear_loader_cache():
    loader_module._cache.clear()
    yield
    loader_module._cache.clear()


@pytest.mark.asyncio
async def test_get_active_demand_predictor_returns_none_when_untrained():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        predictor = await get_active_demand_predictor(session, tenant.id)
        assert predictor is None
        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_get_active_demand_predictor_loads_after_retrain(tmp_path):
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        result = await retrain_demand_model(
            session, tenant.id, triggered_by="test", artifacts_dir=tmp_path,
        )
        assert result["status"] == "ok"

        predictor = await get_active_demand_predictor(session, tenant.id)
        assert predictor is not None
        prediction = predictor.predict(drinks_so_far=50, hour_offset_from_start=3.0)
        assert prediction["predicted_final_total"] > 0

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_get_active_demand_predictor_reloads_on_new_version(tmp_path):
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        await retrain_demand_model(session, tenant.id, triggered_by="test", artifacts_dir=tmp_path)
        first = await get_active_demand_predictor(session, tenant.id)
        assert first is not None

        # Cache hit: same object, no re-unpickle, until version changes.
        cached_again = await get_active_demand_predictor(session, tenant.id)
        assert cached_again is first

        await retrain_demand_model(session, tenant.id, triggered_by="test", artifacts_dir=tmp_path)
        second = await get_active_demand_predictor(session, tenant.id)
        assert second is not None
        assert second is not first

        await delete_tenant_cascade(session, tenant.id)
