"""CLI: build the drinks-demand training grid (historical + current) and
write it to app/modules/predictions/demand/data/*.parquet.

Usage:
    python -m app.scripts.build_demand_training_data \\
        --tenant-id 25ef916c-a288-44ae-b17c-8dfd09390834 \\
        --current-event 6bd035a9-3ab4-4c7f-8f68-c811aef9fa47:sundance14:2026-06-14

Repeatable --current-event event_id:label:date. Historical events (the 9
in nowcast/data/training_transactions.parquet) are always included.

TRAINING-DATA DECISIONS (Day 3 spec, answered here — not silently):
  - Jul-5 (0888f4b7-...) is EXCLUDED entirely, not scaled. It's 75.8%
    line-complete, but the gap is not randomly distributed: 2 bars are
    at exactly 0% coverage (nothing to scale FROM) and the other 3
    bars' losses are scattered across nearly the whole event rather
    than concentrated in one time window (see the Phase 2
    zero-line-order investigation). A single per-event or even
    per-bar scaling factor would misrepresent the TRUE hourly shape at
    exactly the bars/hours it's most needed, which is worse for a
    shape-curve model than leaving the event out entirely.
  - Jul-19 (9ae0dc52-...) is the holdout. It must never be passed to
    --current-event here — this script has no special-case guard
    against it, so don't pass it; the holdout discipline is enforced
    by what you call this with, not by code.
  - The 9 historical (2024/2025) events ARE usable — see
    app/modules/predictions/demand/categorize.py and training_data.py
    docstrings for why, and cbw_audit/raw/ for the verification.

SCOPE: reads customer_purchases (already Slesh-sourced, already
excludes deposits via is_deposit) for the current-year side, and the
nowcast module's existing historical parquet for the historical side.
Never touches recipes, bar_stock, inventory, or alerts.
"""
from __future__ import annotations

import app.models_registry  # noqa: F401 — complete the FK graph for standalone runs

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

import pandas as pd
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.modules.auth.models import Tenant  # noqa: F401 - registers mapper deps
from app.modules.predictions.demand.training_data import (
    DRINK_CATEGORIES,
    build_current_grid,
    build_historical_grid,
    combine_grids,
)

HISTORICAL_TX_PATH = Path(__file__).parent.parent / "modules/predictions/nowcast/data/training_transactions.parquet"
OUTPUT_DIR = Path(__file__).parent.parent / "modules/predictions/demand/data"

_CURRENT_EVENT_PURCHASES_SQL = text("""
    select event_id, customer_key, product_name, category, bar_id, qty, ordered_at
    from customer_purchases
    where event_id = :event_id
      and tenant_id = :tenant_id
      and is_deposit = false
      and category = any(:drink_categories)
""")


async def fetch_current_event_rows(tenant_id: UUID, event_id: UUID, event_date: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        res = await db.execute(_CURRENT_EVENT_PURCHASES_SQL, {
            "tenant_id": tenant_id, "event_id": event_id,
            "drink_categories": list(DRINK_CATEGORIES),
        })
        rows = res.mappings().all()
    return [
        {
            "event_id": str(r["event_id"]),
            "event_date": event_date,
            "ordered_at": r["ordered_at"],
            "bar_id": str(r["bar_id"]) if r["bar_id"] else "unknown",
            "category": r["category"],
            "qty": float(r["qty"]),
        }
        for r in rows
    ]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="build_demand_training_data")
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--current-event", action="append", default=[],
                   help="event_id:label:event_date (YYYY-MM-DD) — repeatable.")
    p.add_argument("--out-suffix", default="",
                   help="Suffix for output filenames, e.g. '_holdout_jul19' for a "
                        "validation run's training-only artifact (keeps it from "
                        "colliding with the real training data files).")
    return p


async def _run(args) -> int:
    tenant_id = UUID(args.tenant_id)

    print(f"Loading historical grid from {HISTORICAL_TX_PATH} ...")
    historical_tx = pd.read_parquet(HISTORICAL_TX_PATH)
    historical_grid = build_historical_grid(historical_tx)
    print(f"  {len(historical_grid.events)} historical events, "
          f"{historical_grid.events['total_drinks'].sum()} total drinks")

    current_grids = []
    for spec in args.current_event:
        event_id_str, label, event_date = spec.split(":")
        print(f"Fetching current-event rows for {label} ({event_id_str}) ...")
        rows = await fetch_current_event_rows(tenant_id, UUID(event_id_str), event_date)
        print(f"  {len(rows)} drink lines")
        current_grids.append(build_current_grid(rows))

    combined = combine_grids(historical_grid, *current_grids)
    print(f"\nCombined: {len(combined.events)} events, {len(combined.grid)} grid rows")
    print(combined.events[["event_id", "source", "total_drinks"]].to_string(index=False))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    events_path = OUTPUT_DIR / f"training_events{args.out_suffix}.parquet"
    grid_path = OUTPUT_DIR / f"training_grid{args.out_suffix}.parquet"
    combined.events.to_parquet(events_path, index=False)
    combined.grid.to_parquet(grid_path, index=False)
    print(f"\nWrote {events_path}")
    print(f"Wrote {grid_path}")
    return 0


def main() -> None:
    p = _build_parser()
    sys.exit(asyncio.run(_run(p.parse_args())))


if __name__ == "__main__":
    main()
