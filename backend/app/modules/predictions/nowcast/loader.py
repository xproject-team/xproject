"""loader.py — serves the active nowcast predictor from model_artifacts.

Mirrors demand/loader.py exactly (which itself mirrors this module's
former get_predictor() singleton-with-reload spirit, adapted for a
DB-backed, versioned, per-tenant artifact instead of a shared parquet
file). Per-tenant cache (dict keyed by tenant_id) — the whole point of
this fix is that there is NO shared state between tenants; the old
process-wide singleton is gone (see predictor.py's module docstring).

Unlike the old eager import-time singleton, this cannot load eagerly —
finding the active row needs a DB session, which only exists inside a
request/job.

DISTINCT FAILURE STATES (same discipline as demand/loader.py, which
itself exists because of a real production incident — see that
module's docstring): "no artifact row exists for this tenant" and "an
artifact row exists but its payload can't be loaded" are DIFFERENT
operational states. The former means retrain_from_completed_events has
never run for this tenant — normal, no alarm, most tenants start here.
The latter means a retrain DID succeed and something is now wrong (a
missing/corrupt payload, an incompatible format_version) — that is
never expected and always logged at ERROR. get_active_nowcast_predictor
returns (predictor, reason) — reason is None on success, else a short
constant a caller can surface verbatim (never another tenant's data).
"""
from __future__ import annotations

import logging
import pickle
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.predictions.models import ModelArtifact
from app.modules.predictions.nowcast.predictor import (
    IncompatibleArtifactFormatError,
    NowcastPredictor,
)
from app.modules.predictions.nowcast.retrain import MODEL_NAME

logger = logging.getLogger(__name__)

NOT_TRAINED_REASON = "nowcast has no training data yet for this tenant"
ARTIFACT_UNAVAILABLE_REASON = "nowcast artifact unavailable"

_cache: dict[UUID, tuple[UUID, NowcastPredictor]] = {}  # tenant_id -> (artifact_id, predictor)


def _load_bundle(artifact_id: UUID, file_bytes: bytes | None) -> dict | None:
    """Logs ERROR and returns None on any failure — this is the
    "trained, but unavailable" state, never silently treated as "not
    trained". Unlike demand/loader.py, no legacy file_path fallback:
    every nowcast model_artifacts row is written post-fix, with
    file_bytes always populated (see retrain.py)."""
    if file_bytes is None:
        logger.error(
            "nowcast model artifact %s: file_bytes is NULL — this should be "
            "impossible for a nowcast row (always written with file_bytes set).",
            artifact_id,
        )
        return None
    try:
        return pickle.loads(file_bytes)
    except pickle.PickleError as e:
        logger.error(
            "nowcast model artifact %s: failed to unpickle file_bytes: %s", artifact_id, e,
        )
        return None


async def get_active_nowcast_predictor(
    db: AsyncSession, tenant_id: UUID,
) -> tuple[NowcastPredictor | None, str | None]:
    """Returns (predictor, reason). reason is None iff predictor is not
    None. Never raises — a model-serving problem must never take down
    the Dashboard's forecast panel; the caller (nowcast/service.py)
    turns a None predictor into an honest "insufficient history"
    response, never a fabricated number and never another tenant's."""
    row = (await db.execute(
        select(ModelArtifact.id, ModelArtifact.file_bytes, ModelArtifact.trained_at).where(
            ModelArtifact.tenant_id == tenant_id,
            ModelArtifact.model_name == MODEL_NAME,
            ModelArtifact.is_active.is_(True),
        )
    )).first()
    if row is None:
        return None, NOT_TRAINED_REASON
    artifact_id, file_bytes, trained_at = row

    cached = _cache.get(tenant_id)
    if cached is not None and cached[0] == artifact_id:
        return cached[1], None

    bundle = _load_bundle(artifact_id, file_bytes)
    if bundle is None:
        return None, ARTIFACT_UNAVAILABLE_REASON

    try:
        predictor = NowcastPredictor.from_bundle(bundle, trained_at=trained_at)
    except IncompatibleArtifactFormatError as e:
        logger.error("nowcast model artifact %s: %s", artifact_id, e)
        return None, ARTIFACT_UNAVAILABLE_REASON
    except KeyError as e:
        logger.error("nowcast model artifact %s: bundle missing expected key %s", artifact_id, e)
        return None, ARTIFACT_UNAVAILABLE_REASON

    _cache[tenant_id] = (artifact_id, predictor)
    return predictor, None
