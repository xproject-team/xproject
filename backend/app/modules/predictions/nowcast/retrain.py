"""Auto-retraining for the "ML Predicted" nowcast (Phase F, re-platformed
2026-08 onto model_artifacts — see predictor.py's module docstring for
why: the old parquet-file persistence was both a cross-tenant leak and
non-durable on Railway's ephemeral container disk).

retrain_from_completed_events() pulls every COMPLETED, training-eligible
event for a tenant, turns its confirmed revenue transactions into the
same shape as the historical Sundance dataset (see backend/scripts/
extract_historical_sundance.py), upserts them by event_id into that
TENANT'S OWN previous training set (loaded from their current active
model_artifacts row, if any — never another tenant's), sanity-fits the
predictor math against the merged data BEFORE writing anything, then
persists a new versioned model_artifacts row with the merged data +
fitted curves pickled into file_bytes. Idempotent — safe to run after
every event completion, including re-runs.

Mirrors demand/retrain.py's persistence pattern as closely as possible:
same MODEL_NAME/ALGORITHM/triggered_by/versioning shape, same "new row +
flip is_active" discipline (the migration's locked architecture: at
most one is_active=TRUE per (tenant_id, model_name)), same best-effort
local file write for same-process debugging only (nothing depends on
it surviving).

Differs from demand/retrain.py in one respect, deliberately: demand's
"historical" component is always freshly re-read from a fixed, git-
tracked parquet file shared by every tenant (HISTORICAL_TX_PATH) — that
is itself the same class of cross-tenant sharing this fix removes from
nowcast, just not in today's scope (nowcast only). Nowcast's historical
component instead lives ONLY inside each tenant's own model_artifacts
row: for Noma Group, seeded once via backend/scripts/
bootstrap_nowcast_artifact.py (the 9-event external Sundance dataset —
verifiably Noma Group's own historical data, not generic sample data);
every other tenant starts with none and accumulates purely from their
own completed events going forward. See that script's docstring.

This module does NOT catch its own exceptions — the caller (the arq
task in app/workers/tasks.py) is responsible for catching, logging, and
returning a structured {"status": "error", ...} result so a retrain
failure never propagates into (or rolls back) the event completion that
triggered it.
"""
from __future__ import annotations

import hashlib
import logging
import pickle
from pathlib import Path
from uuid import UUID

import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event, EventStatus
from app.modules.predictions.models import ModelArtifact
from app.modules.predictions.nowcast.predictor import DATA_DIR, FORMAT_VERSION, fit_shape_and_r2
from app.modules.stock_transactions.models import StockTransaction, TransactionSource

logger = logging.getLogger(__name__)

MODEL_NAME = "nowcast"
ALGORITHM = "shape_curve_v1"  # matches demand/retrain.py's naming for the same fit method
ARTIFACTS_DIR = Path(__file__).parent.parent / "artifacts" / "nowcast"

# Same "confirmed revenue" convention as nowcast/service.py — parent
# transactions only (price_cents non-null), slesh_pos + manual_bartender.
REVENUE_SOURCES = (TransactionSource.SLESH_POS, TransactionSource.MANUAL_BARTENDER)

# Explicit dtypes, not just column names: an all-object-dtype empty
# frame (pd.DataFrame(columns=[...])'s default) concatenated with a
# real, properly-typed frame can leave the MERGED first_tx_time/
# timestamp columns as dtype=object instead of datetime64 in some
# pandas versions — which then breaks fit_shape_and_r2's .dt accessor
# for a tenant's very first retrain (empty existing base). Caught by
# test_retrain_creates_artifact_with_only_this_tenants_event.
_EMPTY_EVENTS_DF = pd.DataFrame({
    "event_id": pd.Series(dtype="object"),
    "event_date": pd.Series(dtype="object"),
    "name": pd.Series(dtype="object"),
    "total_revenue": pd.Series(dtype="float64"),
    "first_tx_time": pd.Series(dtype="datetime64[ns]"),
    "last_tx_time": pd.Series(dtype="datetime64[ns]"),
})
_EMPTY_TX_DF = pd.DataFrame({
    "event_id": pd.Series(dtype="object"),
    "event_date": pd.Series(dtype="object"),
    "timestamp": pd.Series(dtype="datetime64[ns]"),
    "amount_eur": pd.Series(dtype="float64"),
})


async def _event_transactions_df(
    db: AsyncSession, tenant_id: UUID, event: Event,
) -> pd.DataFrame:
    """Confirmed revenue transactions for one event, in the same
    (event_id, event_date, timestamp, amount_eur) shape as the
    historical bootstrap data. Naive (tz-stripped) timestamps — mixing
    tz-aware and naive datetime64 columns in one DataFrame breaks
    pandas' .dt accessor.
    """
    stmt = (
        select(StockTransaction.created_at, StockTransaction.price_cents)
        .where(StockTransaction.tenant_id == tenant_id)
        .where(StockTransaction.event_id == event.id)
        .where(StockTransaction.price_cents.is_not(None))
        .where(StockTransaction.source.in_(REVENUE_SOURCES))
        .order_by(StockTransaction.created_at)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return pd.DataFrame(columns=["event_id", "event_date", "timestamp", "amount_eur"])

    return pd.DataFrame({
        "event_id":   str(event.id),
        "event_date": event.scheduled_at.date(),
        "timestamp":  [pd.Timestamp(r.created_at).tz_localize(None) for r in rows],
        "amount_eur": [r.price_cents / 100.0 for r in rows],
    })


def _upsert_by_event_id(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    """Replace any existing rows sharing an event_id with `incoming`,
    keep everything else. Union of columns — historical-only columns
    stay populated for historical rows and NaN for newly-merged live-DB
    rows; nothing in predictor.py reads those columns today."""
    incoming_ids = set(incoming["event_id"])
    kept = existing[~existing["event_id"].isin(incoming_ids)]
    return pd.concat([kept, incoming], ignore_index=True)


async def _load_existing_bundle_dfs(
    db: AsyncSession, tenant_id: UUID,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """This tenant's own current training basis to upsert into — NEVER
    another tenant's. A tenant with no active artifact yet (the common
    case: no bootstrap, no retrain has run) starts from empty frames,
    not from anyone else's history."""
    row = (await db.execute(
        select(ModelArtifact.file_bytes).where(
            ModelArtifact.tenant_id == tenant_id,
            ModelArtifact.model_name == MODEL_NAME,
            ModelArtifact.is_active.is_(True),
        )
    )).first()
    if row is None or row[0] is None:
        return _EMPTY_EVENTS_DF.copy(), _EMPTY_TX_DF.copy()

    bundle = pickle.loads(row[0])
    return bundle["events_df"], bundle["transactions_df"]


def _next_version(db_versions: list[int]) -> int:
    return (max(db_versions) + 1) if db_versions else 1


async def retrain_from_completed_events(
    db: AsyncSession, tenant_id: UUID, *,
    triggered_by: str, triggered_by_event_id: UUID | None = None,
    artifacts_dir: Path | None = None,
) -> dict:
    """Rebuild this tenant's nowcast training set from every COMPLETED,
    training-eligible event for this tenant, upserted into their own
    prior model_artifacts row (never another tenant's — see
    _load_existing_bundle_dfs). Returns a summary dict; raises on any
    hard failure (refit failure) — the caller decides how to isolate
    that from its own transaction, same contract as
    retrain_demand_model.
    """
    stmt = (
        select(Event)
        .where(Event.tenant_id == tenant_id)
        .where(Event.status == EventStatus.COMPLETED)
        .where(Event.is_training_eligible.is_(True))
    )
    completed_events = (await db.execute(stmt)).scalars().all()

    new_event_rows: list[dict] = []
    new_tx_frames: list[pd.DataFrame] = []
    skipped_no_revenue: list[str] = []

    for event in completed_events:
        tx_df = await _event_transactions_df(db, tenant_id, event)
        if tx_df.empty:
            skipped_no_revenue.append(str(event.id))
            continue
        new_event_rows.append({
            "event_id":      str(event.id),
            "event_date":    event.scheduled_at.date(),
            "name":          event.name,
            "total_revenue": float(tx_df["amount_eur"].sum()),
            "first_tx_time": tx_df["timestamp"].min(),
            "last_tx_time":  tx_df["timestamp"].max(),
        })
        new_tx_frames.append(tx_df)

    if not new_event_rows:
        return {
            "status": "no_completed_events_with_revenue",
            "retrained": False,
            "skipped_no_revenue": skipped_no_revenue,
        }

    new_events_df = pd.DataFrame(new_event_rows)
    new_tx_df = pd.concat(new_tx_frames, ignore_index=True)

    existing_events_df, existing_tx_df = await _load_existing_bundle_dfs(db, tenant_id)
    merged_events_df = _upsert_by_event_id(existing_events_df, new_events_df)
    merged_tx_df = _upsert_by_event_id(existing_tx_df, new_tx_df)

    # Sanity-fit BEFORE writing anything — if the merged data can't be
    # fit, bail out with the old artifact still active rather than
    # writing something the predictor can't load.
    shape_curve, r2_table = fit_shape_and_r2(merged_events_df, merged_tx_df)

    bundle = {
        "format_version": FORMAT_VERSION,
        "events_df": merged_events_df,
        "transactions_df": merged_tx_df,
        "shape_curve": shape_curve,
        "r2_table": r2_table,
        "historical_mean": float(merged_events_df["total_revenue"].mean()),
        "historical_range_eur": (
            float(merged_events_df["total_revenue"].min()),
            float(merged_events_df["total_revenue"].max()),
        ),
        "historical_n": int(len(merged_events_df)),
    }

    target_dir = artifacts_dir or ARTIFACTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    existing_versions = (await db.execute(
        select(ModelArtifact.version).where(
            ModelArtifact.tenant_id == tenant_id, ModelArtifact.model_name == MODEL_NAME,
        )
    )).scalars().all()
    version = _next_version(list(existing_versions))

    file_path = target_dir / f"{MODEL_NAME}_v{version}.pkl"
    file_bytes = pickle.dumps(bundle)
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()

    # Best-effort local write, same-process debugging only — the
    # durable copy is file_bytes on the row below; nothing depends on
    # this surviving (same discipline as demand/retrain.py).
    try:
        with open(file_path, "wb") as f:
            f.write(file_bytes)
    except OSError as e:
        logger.warning(
            "retrain_from_completed_events: local file write failed (non-fatal — "
            "the durable copy is file_bytes on the model_artifacts row): %s", e,
        )

    # Deactivate any current active version for this (tenant, model_name)
    # BEFORE inserting the new active one — the partial unique index
    # would otherwise reject having two is_active=TRUE rows at once.
    await db.execute(
        text("""
            update model_artifacts set is_active = false, deprecated_at = now()
            where tenant_id = :tenant_id and model_name = :model_name and is_active = true
        """),
        {"tenant_id": tenant_id, "model_name": MODEL_NAME},
    )

    training_event_ids = [UUID(eid) for eid in merged_events_df["event_id"] if _looks_like_uuid(eid)]

    artifact = ModelArtifact(
        tenant_id=tenant_id,
        model_name=MODEL_NAME,
        version=version,
        file_path=str(file_path),
        file_size_bytes=len(file_bytes),
        file_sha256=file_sha256,
        file_bytes=file_bytes,
        training_event_ids=training_event_ids,
        n_training_events=int(len(merged_events_df)),
        n_training_rows=int(len(merged_tx_df)),
        feature_names=["elapsed_hour"],
        algorithm=ALGORITHM,
        metrics_json={
            "r2_at_hour_4": float(r2_table.get(4.0, 0.0)),
            "r2_at_hour_8": float(r2_table.get(8.0, 0.0)),
        },
        is_active=True,
        promoted_at=func.now(),
        triggered_by=triggered_by,
        triggered_by_event_id=triggered_by_event_id,
    )
    db.add(artifact)
    await db.commit()

    return {
        "status": "ok",
        "retrained": True,
        "version": version,
        "events_added_or_updated": list(new_events_df["event_id"]),
        "skipped_no_revenue": skipped_no_revenue,
        "training_events_count": int(len(merged_events_df)),
    }


def _looks_like_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False  # historical event_ids are strings like "sundance_2024-06-16", not UUIDs


async def bootstrap_from_static_dataset(
    db: AsyncSession, tenant_id: UUID, *,
    data_dir: Path = DATA_DIR, artifacts_dir: Path | None = None,
) -> dict:
    """One-time seed of a tenant's nowcast model_artifacts row from the
    static, git-tracked historical dataset (app/modules/predictions/
    nowcast/data/*.parquet — the original 9-event external Sundance
    dataset). Used by backend/scripts/bootstrap_nowcast_artifact.py for
    Noma Group specifically — that dataset is verifiably THEIR own
    historical data (see that script's docstring) — never intended to
    seed any other tenant.

    Idempotent: refuses to run (returns status="already_bootstrapped")
    if this tenant already has an active nowcast artifact, whether from
    a prior bootstrap or from a real retrain — never overwrites real
    trained data with the static bootstrap set.
    """
    existing = (await db.execute(
        select(ModelArtifact.id, ModelArtifact.version).where(
            ModelArtifact.tenant_id == tenant_id,
            ModelArtifact.model_name == MODEL_NAME,
            ModelArtifact.is_active.is_(True),
        )
    )).first()
    if existing is not None:
        return {
            "status": "already_bootstrapped",
            "retrained": False,
            "existing_artifact_id": str(existing[0]),
            "existing_version": existing[1],
        }

    events_df = pd.read_parquet(data_dir / "training_events.parquet")
    tx_df = pd.read_parquet(data_dir / "training_transactions.parquet")
    shape_curve, r2_table = fit_shape_and_r2(events_df, tx_df)

    bundle = {
        "format_version": FORMAT_VERSION,
        "events_df": events_df,
        "transactions_df": tx_df,
        "shape_curve": shape_curve,
        "r2_table": r2_table,
        "historical_mean": float(events_df["total_revenue"].mean()),
        "historical_range_eur": (
            float(events_df["total_revenue"].min()),
            float(events_df["total_revenue"].max()),
        ),
        "historical_n": int(len(events_df)),
    }

    target_dir = artifacts_dir or ARTIFACTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"{MODEL_NAME}_v1_bootstrap.pkl"
    file_bytes = pickle.dumps(bundle)
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()
    try:
        with open(file_path, "wb") as f:
            f.write(file_bytes)
    except OSError as e:
        logger.warning(
            "bootstrap_from_static_dataset: local file write failed (non-fatal): %s", e,
        )

    artifact = ModelArtifact(
        tenant_id=tenant_id,
        model_name=MODEL_NAME,
        version=1,
        file_path=str(file_path),
        file_size_bytes=len(file_bytes),
        file_sha256=file_sha256,
        file_bytes=file_bytes,
        training_event_ids=[],  # historical event_ids are strings, not UUIDs
        n_training_events=int(len(events_df)),
        n_training_rows=int(len(tx_df)),
        feature_names=["elapsed_hour"],
        algorithm=ALGORITHM,
        metrics_json={
            "r2_at_hour_4": float(r2_table.get(4.0, 0.0)),
            "r2_at_hour_8": float(r2_table.get(8.0, 0.0)),
        },
        is_active=True,
        promoted_at=func.now(),
        triggered_by="bootstrap_historical_import",
        triggered_by_event_id=None,
    )
    db.add(artifact)
    await db.commit()

    return {
        "status": "ok",
        "retrained": True,
        "version": 1,
        "n_training_events": int(len(events_df)),
        "n_training_rows": int(len(tx_df)),
    }
