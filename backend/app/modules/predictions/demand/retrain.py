"""retrain.py — trains the drinks-demand model from COMPLETED events and
persists it as a versioned model_artifacts row + joblib file.

Mirrors nowcast/retrain.py's isolation contract (this module does NOT
catch its own exceptions — the caller's arq task does, so a retrain
failure never propagates into or rolls back the event completion that
triggered it) and its "sanity-fit before writing anything" discipline.

Persistence differs from nowcast's, deliberately: nowcast overwrites
two parquet files in place (a stateless-singleton design with no
history). This model persists via model_artifacts instead — a NEW
row + NEW file per training run, versioned, with is_active flipped
atomically — because that table's migration docstring locks this
exact pattern ("Pattern A — offline retrain after each event ends...
Versioning: this table + .joblib files on disk... at most one
is_active=TRUE per (tenant_id, model_name)") as the intended
architecture for any new model, and this is the first one to use it.

HOLDOUT: Jul-19 (9ae0dc52-8a01-4998-b430-3814bd8cdabe) was excluded from
training for the Day 3 validation gate (train blind, predict Jul-19,
beat baseline) and only that gate — not a permanent exclusion. That
validation passed (67.1% vs 96.5% MAPE overall; see the Day 3 report).
Per the Day 3 closeout instruction, Jul-19 now trains normally: it is
the closest available analog to the next live event (same venue, bars,
menu, season) and holding it back forever would throw away exactly the
data most relevant to what comes next.

JUL-5 SHAPE-ONLY: Jul-5's per-LINE data has non-random per-bar gaps (2
bars at 0% stock_transaction coverage — the reason it was excluded from
training entirely in the original Day 3 pass), so it still cannot
contribute to category_share or bar_share. But event_orders.
confirmed_line_count is populated for all 4,133 of its orders,
including the 880 with no matching customer_purchases line — the gap is
in the line-to-product join, not in order capture. Its cumulative-count
shape was checked against Sundance 14's known-good shape (max ~4
percentage points of drift at the mid-event peak) and judged close
enough to use as a shape_curve-only contributor via fit_demand_curves'
`shape_only` param — see training_data.build_shape_only_grid.

WEIGHTING: a leave-one-out back-test (app/scripts/demand_loo_experiment.py)
compared uniform event weighting against up-weighting current-season
events (x2/x3/x5) at the venue-total-per-hour grain. Uniform won
outright — up-weighting monotonically INCREASED mean LOO MAPE (37.1% ->
45.3% -> 51.0% -> 58.7%), because with only 2-3 current-season events,
up-weighting them shrinks the effective pool this small-n approach
depends on. No weighting is applied here; fit_demand_curves is called
with weights=None (uniform, its default).
"""
from __future__ import annotations

import hashlib
import pickle
from pathlib import Path
from uuid import UUID

import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event, EventStatus
from app.modules.predictions.demand.predictor import DATA_DIR as _DEMAND_DATA_DIR, fit_demand_curves
from app.modules.predictions.demand.training_data import (
    DRINK_CATEGORIES,
    build_current_grid,
    build_historical_grid,
    build_shape_only_grid,
    combine_grids,
)
from app.modules.predictions.models import ModelArtifact

MODEL_NAME = "demand_forecast"
ALGORITHM = "shape_curve_v1"  # matches nowcast's fit_shape_and_r2 method, extended for bar/category
ARTIFACTS_DIR = Path(__file__).parent.parent / "artifacts" / "demand"
HISTORICAL_TX_PATH = Path(__file__).parent.parent / "nowcast" / "data" / "training_transactions.parquet"

# Jul-5 — see module docstring's JUL-5 SHAPE-ONLY section. Hard-coded like
# the former Jul-19 holdout was: a one-off, deliberate special case, not a
# general mechanism, so it should be a reviewed diff if it ever changes.
_JUL5_SHAPE_ONLY_EVENT_ID = UUID("0888f4b7-7030-426b-815c-938e6ca447a6")

_PURCHASE_ROWS_SQL = text("""
    select customer_key, product_name, category, bar_id, qty, ordered_at
    from customer_purchases
    where event_id = :event_id and tenant_id = :tenant_id
      and is_deposit = false
      and category = any(:drink_categories)
""")

_JUL5_ORDER_ROWS_SQL = text("""
    select created_at_slesh as ordered_at, confirmed_line_count as count
    from event_orders
    where event_id = :event_id and tenant_id = :tenant_id
""")


async def _event_purchase_rows(db: AsyncSession, tenant_id: UUID, event: Event) -> list[dict]:
    res = await db.execute(_PURCHASE_ROWS_SQL, {
        "event_id": event.id, "tenant_id": tenant_id, "drink_categories": list(DRINK_CATEGORIES),
    })
    rows = res.mappings().all()
    return [
        {
            "event_id": str(event.id),
            "event_date": event.scheduled_at.date().isoformat(),
            "ordered_at": pd.Timestamp(r["ordered_at"]),
            "bar_id": str(r["bar_id"]) if r["bar_id"] else "unknown",
            "category": r["category"],
            "qty": float(r["qty"]),
        }
        for r in rows
    ]


async def _jul5_shape_only_grid(db: AsyncSession, tenant_id: UUID) -> pd.DataFrame:
    res = await db.execute(_JUL5_ORDER_ROWS_SQL, {
        "event_id": _JUL5_SHAPE_ONLY_EVENT_ID, "tenant_id": tenant_id,
    })
    rows = res.mappings().all()
    if not rows:
        return pd.DataFrame(columns=["event_id", "hour_of_event", "count"])
    order_rows = [
        {"event_id": "jul5", "ordered_at": pd.Timestamp(r["ordered_at"]), "count": float(r["count"])}
        for r in rows
    ]
    return build_shape_only_grid(order_rows)


def _next_version(db_versions: list[int]) -> int:
    return (max(db_versions) + 1) if db_versions else 1


async def retrain_demand_model(
    db: AsyncSession, tenant_id: UUID, *, triggered_by: str, triggered_by_event_id: UUID | None = None,
    artifacts_dir: Path | None = None,
) -> dict:
    """Rebuild the demand model from every COMPLETED, training-eligible
    event for this tenant, plus the fixed historical (2024/2025) grid and
    Jul-5's shape-only contribution. Returns a summary dict; raises on any
    hard failure — the caller (the arq task) decides how to isolate that
    from its own transaction, same contract as retrain_predictor.
    """
    stmt = (
        select(Event)
        .where(Event.tenant_id == tenant_id)
        .where(Event.status == EventStatus.COMPLETED)
        .where(Event.is_training_eligible.is_(True))
    )
    completed_events = (await db.execute(stmt)).scalars().all()

    current_grids = []
    skipped_no_drinks: list[str] = []
    for event in completed_events:
        rows = await _event_purchase_rows(db, tenant_id, event)
        if not rows:
            skipped_no_drinks.append(str(event.id))
            continue
        current_grids.append(build_current_grid(rows))

    historical_tx = pd.read_parquet(HISTORICAL_TX_PATH)
    historical_grid = build_historical_grid(historical_tx)

    combined = combine_grids(historical_grid, *current_grids)
    if combined.events.empty:
        return {"status": "no_training_data", "retrained": False}

    shape_only = await _jul5_shape_only_grid(db, tenant_id)

    # Sanity-fit BEFORE writing anything — same discipline as
    # nowcast/retrain.py: a fit that can't be computed must not reach disk.
    # weights=None: uniform, per the LOO finding in the module docstring.
    shape_curve, r2_table, category_share, bar_share = fit_demand_curves(
        combined.events, combined.grid, None, shape_only,
    )

    bundle = {
        "shape_curve": shape_curve,
        "r2_table": r2_table,
        "category_share": category_share,
        "bar_share": bar_share,
        "historical_mean_total": float(combined.events["total_drinks"].mean()),
        "historical_n": int(len(combined.events)),
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
    with open(file_path, "wb") as f:
        pickle.dump(bundle, f)
    file_bytes = file_path.read_bytes()
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()

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

    training_event_ids = [UUID(eid) for eid in combined.events["event_id"] if _looks_like_uuid(eid)]

    artifact = ModelArtifact(
        tenant_id=tenant_id,
        model_name=MODEL_NAME,
        version=version,
        file_path=str(file_path),
        file_size_bytes=len(file_bytes),
        file_sha256=file_sha256,
        training_event_ids=training_event_ids,
        n_training_events=int(len(combined.events)),
        n_training_rows=int(len(combined.grid)),
        feature_names=["bar_rank", "hour_of_event", "category"],
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
        "n_training_events": int(len(combined.events)),
        "n_training_rows": int(len(combined.grid)),
        "skipped_no_drinks": skipped_no_drinks,
        "file_path": str(file_path),
    }


def _looks_like_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False  # historical event_ids are strings like "sundance_2024-06-16", not UUIDs
