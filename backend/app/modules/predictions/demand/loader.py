"""loader.py — serves the active demand model from model_artifacts.

Mirrors nowcast/predictor.py's get_predictor() singleton-with-reload
spirit, adapted for a DB-backed, versioned artifact instead of a static
parquet file: there's no file mtime to poll, so this checks the active
row's id cheaply on every call and only unpickles the file when it
changes. Per-tenant cache (dict keyed by tenant_id) since this is a
multi-tenant system; nowcast's single global singleton doesn't apply
here.

Unlike nowcast's eager import-time singleton, this cannot load eagerly
— finding the active row needs a DB session, which only exists inside
a request/job. Callers get None when no active artifact exists yet
(retrain_demand_model has never run for this tenant) and must degrade
gracefully — see customer_intelligence/service.py.
"""
from __future__ import annotations

import pickle
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.predictions.demand.predictor import DemandPredictor
from app.modules.predictions.demand.retrain import MODEL_NAME
from app.modules.predictions.models import ModelArtifact

_cache: dict[UUID, tuple[UUID, DemandPredictor]] = {}  # tenant_id -> (artifact_id, predictor)


async def get_active_demand_predictor(db: AsyncSession, tenant_id: UUID) -> DemandPredictor | None:
    """Returns None if no active demand_forecast artifact exists yet for
    this tenant. Never raises on a missing/unreadable artifact file —
    that would take down the whole customer-intelligence panel over a
    model-serving problem; callers treat None the same as "not trained
    yet" and render the rest of the panel regardless."""
    row = (await db.execute(
        select(ModelArtifact.id, ModelArtifact.file_path).where(
            ModelArtifact.tenant_id == tenant_id,
            ModelArtifact.model_name == MODEL_NAME,
            ModelArtifact.is_active.is_(True),
        )
    )).first()
    if row is None:
        return None
    artifact_id, file_path = row

    cached = _cache.get(tenant_id)
    if cached is not None and cached[0] == artifact_id:
        return cached[1]

    try:
        with open(file_path, "rb") as f:
            bundle = pickle.load(f)
        predictor = DemandPredictor.from_bundle(bundle)
    except (OSError, pickle.PickleError, KeyError):
        return None

    _cache[tenant_id] = (artifact_id, predictor)
    return predictor
