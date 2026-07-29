"""CLI: leave-one-out back-test to decide whether up-weighting current-
season events (vs. the 2024/2025 historical set) actually reduces the
demand model's error, per the Day 3 closeout request. Do NOT apply a
weighting scheme without running this first — "consider weighting...
report whether weighting improves leave-one-out error or not; do not
apply it blindly."

Protocol: for each candidate weight scheme (uniform, and current-season
multiplier in {2, 3, 5}), and for each of the 11 full training events in
turn, fit on the other 10 (weighted per the scheme) plus Jul-5's
shape-only contribution (always included — it's a shape-curve-only
signal, never an evaluation target, see training_data.build_shape_only_grid),
then score the held-out event at the venue-total-per-hour grain (the one
grain the Day 3 aggregate-accuracy pass showed to be defensible) using
the same actuals-through-h -> predict h+1 checkpoint protocol
validate_demand_model.py uses for Jul-19. Report mean LOO MAPE/MAE per
scheme; the winning scheme is whichever minimizes mean LOO error — if
that is the uniform (w=1) scheme, weighting is NOT applied in production.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from app.modules.predictions.demand.predictor import BAR_RANKS, HOUR_GRID, DemandPredictor
from app.modules.predictions.demand.training_data import (
    DRINK_CATEGORIES,
    build_current_grid,
    build_historical_grid,
    build_shape_only_grid,
    combine_grids,
)
from app.scripts.validate_demand_model import _mae, _mape


def _load_all():
    ml_data_dir = Path(__file__).parent / "ml_data"
    raw = json.load(open(ml_data_dir / "purchases_raw.json"))

    sundance14_rows = [
        {**r, "event_id": "sundance14", "event_date": "2026-06-14", "ordered_at": pd.Timestamp(r["ordered_at"])}
        for r in raw["sundance14"]
    ]
    jul19_rows = [
        {**r, "event_id": "jul19", "event_date": "2026-07-19", "ordered_at": pd.Timestamp(r["ordered_at"])}
        for r in raw["jul19"]
    ]
    s14_grid = build_current_grid(sundance14_rows)
    jul19_grid = build_current_grid(jul19_rows)

    hist_tx = pd.read_parquet(
        Path(__file__).parent.parent / "modules/predictions/nowcast/data/training_transactions.parquet"
    )
    hist_grid = build_historical_grid(hist_tx)

    jul5_orders = json.load(open(ml_data_dir / "jul5_orders_raw.json"))
    jul5_rows = [{"event_id": "jul5", "ordered_at": pd.Timestamp(r["ordered_at"]), "count": r["count"]}
                 for r in jul5_orders]
    jul5_shape_only = build_shape_only_grid(jul5_rows)

    full = combine_grids(hist_grid, s14_grid, jul19_grid)
    return full, jul5_shape_only


def _venue_hour_checkpoint_eval(predictor: DemandPredictor, held_out_grid: pd.DataFrame) -> list[tuple[float, float]]:
    """actuals-through-h -> predict h+1, venue-wide total per hour. Same
    protocol as validate_demand_model.run_validation, collapsed straight
    to the venue-total grain since that's all this experiment needs."""
    pairs = []
    for h_now in range(0, 9):
        target_hour = h_now + 1
        observed_so_far = held_out_grid[held_out_grid["hour_of_event"] <= h_now]["drinks_count"].sum()
        prediction = predictor.predict(float(observed_so_far), float(h_now))
        predicted_next = prediction["predicted_by_hour"].get(round(float(target_hour), 1), {})
        predicted_total = sum(
            predicted_next.get(rank, {}).get(cat, 0.0)
            for rank in BAR_RANKS for cat in DRINK_CATEGORIES
        )
        actual_total = float(
            held_out_grid[held_out_grid["hour_of_event"] == target_hour]["drinks_count"].sum()
        )
        pairs.append((actual_total, predicted_total))
    return pairs


def run_loo(full, jul5_shape_only, weight_scheme_name: str, current_multiplier: float) -> dict:
    event_ids = full.events["event_id"].unique().tolist()
    source_by_event = full.events.set_index("event_id")["source"]

    all_pairs = []
    for held_out in event_ids:
        train_events = full.events[full.events["event_id"] != held_out]
        train_grid = full.grid[full.grid["event_id"] != held_out]
        held_out_grid = full.grid[full.grid["event_id"] == held_out]

        weights = pd.Series(1.0, index=train_events["event_id"])
        if current_multiplier != 1.0:
            is_current = source_by_event.reindex(weights.index) == "current"
            weights[is_current] = current_multiplier

        shape_only = jul5_shape_only.copy()
        if current_multiplier != 1.0 and not shape_only.empty:
            # Jul-5 is current-season too; give it the same multiplier by
            # folding it into the weights series fit_demand_curves reads.
            weights["jul5"] = current_multiplier

        predictor = DemandPredictor.from_dataframes(train_events, train_grid, weights, shape_only)
        all_pairs.extend(_venue_hour_checkpoint_eval(predictor, held_out_grid))

    mape, n_used, n_excl = _mape(all_pairs)
    mae, n = _mae(all_pairs)
    return {"scheme": weight_scheme_name, "mape": mape, "mape_n": n_used, "mape_excl": n_excl, "mae": mae, "mae_n": n}


def main() -> None:
    full, jul5_shape_only = _load_all()
    print(f"Full training pool for LOO: {len(full.events)} events "
          f"(includes Jul-19, excludes nothing) + Jul-5 shape-only ({jul5_shape_only['event_id'].nunique()} event)")
    print(full.events[["event_id", "source", "total_drinks"]].to_string(index=False))

    schemes = [("uniform (w=1)", 1.0), ("current x2", 2.0), ("current x3", 3.0), ("current x5", 5.0)]
    results = [run_loo(full, jul5_shape_only, name, mult) for name, mult in schemes]

    print("\n" + "=" * 78)
    print("LEAVE-ONE-OUT: venue-total-per-hour MAPE/MAE, one fold per training event")
    print("=" * 78)
    for r in results:
        print(f"  {r['scheme']:>14s}   MAPE: {r['mape']:6.1f}% (n={r['mape_n']}, excl={r['mape_excl']})"
              f"   MAE: {r['mae']:6.2f} drinks (n={r['mae_n']})")

    best = min(results, key=lambda r: r["mape"])
    baseline = results[0]
    print(f"\nBest scheme by LOO MAPE: {best['scheme']}")
    if best["scheme"] == baseline["scheme"]:
        print("DECISION: uniform weighting wins — do NOT apply a current-season multiplier in production.")
    else:
        improvement = baseline["mape"] - best["mape"]
        print(f"DECISION: {best['scheme']} beats uniform by {improvement:.1f} MAPE points — "
              f"{'apply it' if improvement > 2.0 else 'marginal; treat as noise, do NOT apply it'} in production.")


if __name__ == "__main__":
    main()
