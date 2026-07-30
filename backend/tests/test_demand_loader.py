"""Tests for demand/loader.py — the read path model_artifacts never had
before this: get_active_demand_predictor unpickles the active artifact
and caches it per-tenant, invalidating only when the active row changes.

Also covers the 2026-07-30 fix (migration af1): "no artifact row" and
"artifact row exists but its payload can't be loaded" must report
DIFFERENT reasons (NOT_TRAINED_REASON vs ARTIFACT_UNAVAILABLE_REASON) —
see loader.py's module docstring for the production incident (v3's
local file vanished after a redeploy; is_active=true survived in
Postgres pointing at nothing, and the old code reported "not trained",
which was wrong).
"""
from __future__ import annotations

from sqlalchemy import select

import pytest

from app.modules.predictions.demand import loader as loader_module
from app.modules.predictions.demand.loader import (
    ARTIFACT_UNAVAILABLE_REASON,
    NOT_TRAINED_REASON,
    get_active_demand_predictor,
)
from app.modules.predictions.demand.retrain import retrain_demand_model
from app.modules.predictions.models import ModelArtifact
from tests.fixtures.alerts.factories import delete_tenant_cascade, make_tenant
from tests.fixtures.alerts.session import TestSessionLocal


@pytest.fixture(autouse=True)
def _clear_loader_cache():
    loader_module._cache.clear()
    yield
    loader_module._cache.clear()


@pytest.mark.asyncio
async def test_get_active_demand_predictor_returns_not_trained_when_no_row():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        predictor, reason = await get_active_demand_predictor(session, tenant.id)
        assert predictor is None
        assert reason == NOT_TRAINED_REASON
        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_get_active_demand_predictor_loads_after_retrain(tmp_path):
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        result = await retrain_demand_model(
            session, tenant.id, triggered_by="test", artifacts_dir=tmp_path,
        )
        assert result["status"] == "ok"

        predictor, reason = await get_active_demand_predictor(session, tenant.id)
        assert predictor is not None
        assert reason is None
        prediction = predictor.predict(drinks_so_far=50, hour_offset_from_start=3.0)
        assert prediction["predicted_final_total"] > 0

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_get_active_demand_predictor_reloads_on_new_version(tmp_path):
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        await retrain_demand_model(session, tenant.id, triggered_by="test", artifacts_dir=tmp_path)
        first, _ = await get_active_demand_predictor(session, tenant.id)
        assert first is not None

        # Cache hit: same object, no re-unpickle, until version changes.
        cached_again, _ = await get_active_demand_predictor(session, tenant.id)
        assert cached_again is first

        await retrain_demand_model(session, tenant.id, triggered_by="test", artifacts_dir=tmp_path)
        second, _ = await get_active_demand_predictor(session, tenant.id)
        assert second is not None
        assert second is not first

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_reads_from_file_bytes_even_when_local_file_is_gone(tmp_path):
    """The actual production scenario: file_bytes survives (it's in
    Postgres); the local file does not (ephemeral container disk,
    wiped by a redeploy). Loading must still succeed from bytes alone."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        result = await retrain_demand_model(
            session, tenant.id, triggered_by="test", artifacts_dir=tmp_path,
        )
        assert result["status"] == "ok"

        # Simulate the redeploy: the local file is gone, file_bytes is not.
        import os
        os.remove(result["file_path"])

        predictor, reason = await get_active_demand_predictor(session, tenant.id)
        assert predictor is not None
        assert reason is None

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_missing_file_bytes_and_missing_file_reports_artifact_unavailable_not_not_trained(tmp_path):
    """The exact bug this migration fixes, reproduced directly: an
    active row exists (so this is NOT "never trained"), but neither
    file_bytes nor the local file can produce a bundle. Must report
    ARTIFACT_UNAVAILABLE_REASON, never NOT_TRAINED_REASON."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        result = await retrain_demand_model(
            session, tenant.id, triggered_by="test", artifacts_dir=tmp_path,
        )
        assert result["status"] == "ok"

        import os
        os.remove(result["file_path"])
        await session.execute(
            ModelArtifact.__table__.update()
            .where(ModelArtifact.tenant_id == tenant.id)
            .values(file_bytes=None)
        )
        await session.commit()

        predictor, reason = await get_active_demand_predictor(session, tenant.id)
        assert predictor is None
        assert reason == ARTIFACT_UNAVAILABLE_REASON
        assert reason != NOT_TRAINED_REASON

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_incompatible_format_version_reports_artifact_unavailable(tmp_path):
    """A row whose bundle predates (or mismatches) FORMAT_VERSION must
    fail loudly (logged) but still surface as a graceful
    ARTIFACT_UNAVAILABLE_REASON to the API — not an unhandled exception,
    not "not trained"."""
    import pickle

    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        result = await retrain_demand_model(
            session, tenant.id, triggered_by="test", artifacts_dir=tmp_path,
        )
        assert result["status"] == "ok"

        row = (await session.execute(
            select(ModelArtifact).where(ModelArtifact.tenant_id == tenant.id)
        )).scalar_one()
        bundle = pickle.loads(row.file_bytes)
        bundle["format_version"] = 999
        row.file_bytes = pickle.dumps(bundle)
        await session.commit()

        predictor, reason = await get_active_demand_predictor(session, tenant.id)
        assert predictor is None
        assert reason == ARTIFACT_UNAVAILABLE_REASON

        await delete_tenant_cascade(session, tenant.id)
