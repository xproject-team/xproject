"""loader.py — serves the active demand model from model_artifacts.

Mirrors nowcast/predictor.py's get_predictor() singleton-with-reload
spirit, adapted for a DB-backed, versioned artifact instead of a static
parquet file: there's no file mtime to poll, so this checks the active
row's id cheaply on every call and only unpickles the bundle when it
changes. Per-tenant cache (dict keyed by tenant_id) since this is a
multi-tenant system; nowcast's single global singleton doesn't apply
here.

Unlike nowcast's eager import-time singleton, this cannot load eagerly
— finding the active row needs a DB session, which only exists inside
a request/job.

DISTINCT FAILURE STATES (2026-07-30 fix — see migration af1's docstring
for the incident this addresses): "no artifact row exists" and "an
artifact row exists but its payload can't be loaded" are DIFFERENT
operational states and must be reported differently. The former means
retrain_demand_model has never run for this tenant — normal, no alarm.
The latter means a model WAS trained and something is now wrong (a
missing/corrupt payload, an incompatible format_version) — that is
never expected and always logged at ERROR, because a demand-forecaster
"model artifact unavailable" report needs someone to look, not to be
lumped in with "haven't trained yet" the way a bare `return None` used
to. get_active_demand_predictor returns (predictor, reason) — reason is
None on success, else a short constant a caller can surface verbatim.
"""
from __future__ import annotations

import logging
import pickle
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.predictions.demand.predictor import DemandPredictor, IncompatibleArtifactFormatError
from app.modules.predictions.demand.retrain import MODEL_NAME
from app.modules.predictions.models import ModelArtifact

logger = logging.getLogger(__name__)

NOT_TRAINED_REASON = "demand model not yet trained"
ARTIFACT_UNAVAILABLE_REASON = "model artifact unavailable"

_cache: dict[UUID, tuple[UUID, DemandPredictor]] = {}  # tenant_id -> (artifact_id, predictor)


def _load_bundle(artifact_id: UUID, file_bytes: bytes | None, file_path: str) -> dict | None:
    """Prefers file_bytes (durable, in Postgres); falls back to
    file_path only for rows written before migration af1. Logs ERROR
    and returns None on any failure — this is the "trained, but
    unavailable" state, never silently treated as "not trained"."""
    if file_bytes is not None:
        try:
            return pickle.loads(file_bytes)
        except pickle.PickleError as e:
            logger.error(
                "demand model artifact %s: failed to unpickle file_bytes: %s", artifact_id, e,
            )
            return None

    logger.warning(
        "demand model artifact %s: file_bytes is NULL (written before migration af1) — "
        "falling back to file_path %s, which is local container disk and may not exist "
        "if the container has restarted since this artifact was trained.",
        artifact_id, file_path,
    )
    try:
        with open(file_path, "rb") as f:
            return pickle.load(f)
    except (OSError, pickle.PickleError) as e:
        logger.error(
            "demand model artifact %s: failed to load fallback file_path %s: %s",
            artifact_id, file_path, e,
        )
        return None


async def get_active_demand_predictor(
    db: AsyncSession, tenant_id: UUID,
) -> tuple[DemandPredictor | None, str | None]:
    """Returns (predictor, reason). reason is None iff predictor is not
    None. Never raises — a model-serving problem must never take down
    the rest of the customer-intelligence panel."""
    row = (await db.execute(
        select(ModelArtifact.id, ModelArtifact.file_path, ModelArtifact.file_bytes).where(
            ModelArtifact.tenant_id == tenant_id,
            ModelArtifact.model_name == MODEL_NAME,
            ModelArtifact.is_active.is_(True),
        )
    )).first()
    if row is None:
        return None, NOT_TRAINED_REASON
    artifact_id, file_path, file_bytes = row

    cached = _cache.get(tenant_id)
    if cached is not None and cached[0] == artifact_id:
        return cached[1], None

    bundle = _load_bundle(artifact_id, file_bytes, file_path)
    if bundle is None:
        return None, ARTIFACT_UNAVAILABLE_REASON

    try:
        predictor = DemandPredictor.from_bundle(bundle)
    except IncompatibleArtifactFormatError as e:
        logger.error("demand model artifact %s: %s", artifact_id, e)
        return None, ARTIFACT_UNAVAILABLE_REASON
    except KeyError as e:
        logger.error("demand model artifact %s: bundle missing expected key %s", artifact_id, e)
        return None, ARTIFACT_UNAVAILABLE_REASON

    _cache[tenant_id] = (artifact_id, predictor)
    return predictor, None
