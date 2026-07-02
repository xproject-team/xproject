"""Auto-retraining for the "ML Predicted" nowcast (Phase F).

retrain_from_completed_events() pulls every COMPLETED event for a
tenant, turns its confirmed revenue transactions into the same shape
as the historical Sundance parquet (see backend/scripts/
extract_historical_sundance.py), upserts them into the existing
training set by event_id (idempotent — safe to run after every event
completion, including re-runs), sanity-fits the predictor math against
the merged data BEFORE touching anything on disk, then writes the two
parquet files atomically (write to a .tmp file in the same directory,
then rename — a rename on the same filesystem is atomic, so a reader
never observes a half-written file).

This module does NOT catch its own exceptions — the caller (the arq
task in app/workers/tasks.py) is responsible for catching, logging,
and returning a structured {"status": "error", ...} result so a
retrain failure never propagates into (or rolls back) the event
completion that triggered it. See that task's docstring for the
isolation contract.

Does NOT touch the live predictor singleton directly — get_predictor()
in predictor.py polls the parquet files' mtime and reloads itself (see
that module's "Process-wide singleton" section). This keeps retrain.py
usable from a separate worker process without needing IPC.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event, EventStatus
from app.modules.predictions.nowcast.predictor import DATA_DIR, fit_shape_and_r2
from app.modules.stock_transactions.models import StockTransaction, TransactionSource

# Same "confirmed revenue" convention as nowcast/service.py — parent
# transactions only (price_cents non-null), slesh_pos + manual_bartender.
REVENUE_SOURCES = (TransactionSource.SLESH_POS, TransactionSource.MANUAL_BARTENDER)


async def _event_transactions_df(
    db: AsyncSession, tenant_id: UUID, event: Event,
) -> pd.DataFrame:
    """Confirmed revenue transactions for one event, in the same
    (event_id, event_date, timestamp, amount_eur) shape as
    training_transactions.parquet. Naive (tz-stripped) timestamps to
    match the historical parquet's dtype — mixing tz-aware and naive
    datetime64 columns in one DataFrame breaks pandas' .dt accessor.
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
    (unique_customers, recharge_total_eur, etc.) stay populated for
    historical rows and NaN for newly-merged live-DB rows; nothing in
    predictor.py reads those columns today."""
    incoming_ids = set(incoming["event_id"])
    kept = existing[~existing["event_id"].isin(incoming_ids)]
    return pd.concat([kept, incoming], ignore_index=True)


def _atomic_write_parquet(df: pd.DataFrame, target: Path) -> None:
    tmp = target.with_name(target.name + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(target)  # atomic rename, same filesystem


async def retrain_from_completed_events(
    db: AsyncSession, tenant_id: UUID, data_dir: Path = DATA_DIR,
) -> dict:
    """Rebuild the nowcast training set from every COMPLETED,
    training-eligible event for this tenant. Returns a summary dict;
    raises on any hard failure (missing parquet, refit failure) — the
    caller decides how to isolate that from its own transaction.

    is_training_eligible (events table, migration aa3) is the
    contamination guard flagged in the Phase F report: the dev DB has
    16+ COMPLETED events that are simulation/test/seed fixtures, not
    real Sundance nights, and would otherwise get silently merged into
    the production training parquet. Backfilled false for names
    matching SIMULATION/TEST/SMOKE/EXAMPLE/TRIM (case-insensitive
    substring) — NOTE this is a known-imperfect, literal keyword list;
    e.g. "Sim Sundance 2025-06-15" doesn't match "SIMULATION" and is
    still marked eligible. See the migration's docstring.
    """
    stmt = (
        select(Event)
        .where(Event.tenant_id == tenant_id)
        .where(Event.status == EventStatus.COMPLETED)
        .where(Event.is_training_eligible.is_(True))
    )
    completed_events = (await db.execute(stmt)).scalars().all()

    existing_events_df = pd.read_parquet(data_dir / "training_events.parquet")
    existing_tx_df = pd.read_parquet(data_dir / "training_transactions.parquet")

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

    merged_events_df = _upsert_by_event_id(existing_events_df, new_events_df)
    merged_tx_df = _upsert_by_event_id(existing_tx_df, new_tx_df)

    # Sanity-fit BEFORE writing anything to disk — if the merged data
    # can't be fit (e.g. a degenerate single-event set), we bail out
    # with the old parquet still intact rather than writing something
    # the predictor can't load.
    fit_shape_and_r2(merged_events_df, merged_tx_df)

    _atomic_write_parquet(merged_events_df, data_dir / "training_events.parquet")
    _atomic_write_parquet(merged_tx_df, data_dir / "training_transactions.parquet")

    return {
        "status": "ok",
        "retrained": True,
        "events_added_or_updated": list(new_events_df["event_id"]),
        "skipped_no_revenue": skipped_no_revenue,
        "training_events_count": int(len(merged_events_df)),
    }
