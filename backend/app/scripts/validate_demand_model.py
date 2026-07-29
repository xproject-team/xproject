"""CLI: validate the drinks-demand model against the Jul-19 holdout.

Protocol: for each "we're h hours into the event" checkpoint (h = 0..8),
use ONLY Jul-19's actuals through hour h to predict the NEXT hour
(h+1) — the actionable "what do we need for the coming hour" forecast
this model exists for. Compare against:
  (a) the model's prediction
  (b) a naive baseline: Sundance 14's raw (same bar-rank, same
      category, same hour-of-event) count, unscaled — "previous event,
      same hour, same bar" per the Day 3 spec, with "same bar" read as
      "same bar RANK" since bar identity does not transfer across
      events (see training_data.py). Sundance 14, not Jul-5, is the
      "previous event" — Jul-5 is excluded from training for the
      documented bar-specific data-completeness reason and using it as
      a baseline reference would hit the exact same problem.

CAVEAT, stated plainly: bar-rank assignment for Jul-19's actuals uses
its FINAL (end-of-event) total-volume ranking throughout, not a
rolling rank computed only from actuals-through-that-hour. A fully
causal live deployment would need the latter (early-hour rank can
differ from final rank); this validation's bar-level numbers are
therefore a mild best-case simplification on the bar dimension
specifically. The overall-total and category-level numbers are NOT
affected by this — they don't depend on bar rank at all.

MAPE convention: cells where the ACTUAL count is 0 are excluded from
the MAPE denominator (undefined otherwise) and the excluded count is
reported alongside every MAPE number — never silently dropped.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from app.modules.predictions.demand.predictor import BAR_RANKS, HOUR_GRID, DemandPredictor
from app.modules.predictions.demand.training_data import DRINK_CATEGORIES, build_current_grid


def _mape(pairs: list[tuple[float, float]]) -> tuple[float, int, int]:
    """pairs: list of (actual, predicted). Returns (mape_pct, n_used, n_excluded_zero_actual)."""
    used = [(a, p) for a, p in pairs if a > 0]
    excluded = len(pairs) - len(used)
    if not used:
        return float("nan"), 0, excluded
    errs = [abs(a - p) / a for a, p in used]
    return 100.0 * float(np.mean(errs)), len(used), excluded


def _mae(pairs: list[tuple[float, float]]) -> tuple[float, int]:
    """pairs: list of (actual, predicted). Returns (mae_drinks, n). Unlike
    _mape, zero-actual cells are NOT excluded — MAE is well-defined there
    and dropping them would understate error at low-volume cells/hours."""
    if not pairs:
        return float("nan"), 0
    errs = [abs(a - p) for a, p in pairs]
    return float(np.mean(errs)), len(pairs)


def run_validation(predictor: DemandPredictor, jul19_grid: pd.DataFrame,
                    sundance14_grid: pd.DataFrame) -> dict:
    checkpoints = range(0, 9)  # "h hours in" -> predict hour h+1

    all_pairs: list[tuple[float, float, dict]] = []       # (actual, predicted, meta) for model
    all_baseline_pairs: list[tuple[float, float, dict]] = []  # (actual, baseline, meta)

    for h_now in checkpoints:
        target_hour = h_now + 1
        if target_hour not in HOUR_GRID:
            continue

        observed_so_far = jul19_grid[jul19_grid["hour_of_event"] <= h_now]["drinks_count"].sum()
        prediction = predictor.predict(float(observed_so_far), float(h_now))
        predicted_next = prediction["predicted_by_hour"].get(round(float(target_hour), 1), {})

        actual_next = (
            jul19_grid[jul19_grid["hour_of_event"] == target_hour]
            .groupby(["bar_rank", "category"])["drinks_count"].sum()
        )
        baseline_next = (
            sundance14_grid[sundance14_grid["hour_of_event"] == target_hour]
            .groupby(["bar_rank", "category"])["drinks_count"].sum()
        )

        for rank in BAR_RANKS:
            for cat in DRINK_CATEGORIES:
                actual = float(actual_next.get((rank, cat), 0))
                predicted = float(predicted_next.get(rank, {}).get(cat, 0.0))
                baseline = float(baseline_next.get((rank, cat), 0))
                meta = {"hour": target_hour, "bar_rank": rank, "category": cat, "confidence": prediction["confidence"]}
                all_pairs.append((actual, predicted, meta))
                all_baseline_pairs.append((actual, baseline, meta))

    def _breakdown(pairs, key):
        groups = defaultdict(list)
        for a, p, meta in pairs:
            groups[meta[key]].append((a, p))
        return {k: _mape(v) for k, v in sorted(groups.items())}

    overall = _mape([(a, p) for a, p, _ in all_pairs])
    overall_baseline = _mape([(a, p) for a, p, _ in all_baseline_pairs])

    return {
        "overall_model_mape": overall,
        "overall_baseline_mape": overall_baseline,
        "model_by_category": _breakdown(all_pairs, "category"),
        "baseline_by_category": _breakdown(all_baseline_pairs, "category"),
        "model_by_bar_rank": _breakdown(all_pairs, "bar_rank"),
        "baseline_by_bar_rank": _breakdown(all_baseline_pairs, "bar_rank"),
        "model_by_hour": _breakdown(all_pairs, "hour"),
        "baseline_by_hour": _breakdown(all_baseline_pairs, "hour"),
        "n_checkpoints": len(list(checkpoints)),
        # Raw cell-level (hour, bar_rank, category) triples — the aggregate
        # report sums these UP to coarser grains before scoring, rather than
        # averaging cell-level errors, so the aggregation matches what the
        # panel will actually display (a single number per hour/category/bar,
        # not an average of many noisy per-cell percentages).
        "raw_pairs": all_pairs,
        "raw_baseline_pairs": all_baseline_pairs,
    }


def _aggregate_sum(pairs: list[tuple[float, float, dict]], group_keys: tuple[str, ...]) -> dict:
    """Sum actual and predicted within each group (e.g. group_keys=('hour',)
    sums every bar_rank/category cell sharing an hour into one venue-wide
    total for that hour), returning {group_key_tuple: (actual_sum, predicted_sum)}."""
    sums: dict = defaultdict(lambda: [0.0, 0.0])
    for a, p, meta in pairs:
        key = tuple(meta[k] for k in group_keys)
        sums[key][0] += a
        sums[key][1] += p
    return {k: (v[0], v[1]) for k, v in sums.items()}


def aggregate_validation(results: dict) -> dict:
    """Re-score the same Jul-19 checkpoints at the three grains the panel
    will actually display, per the Day 3 closeout request: cell-level MAPE
    (bar_rank x category x hour) is dominated by small-count noise — 174/270
    cells had zero actuals — so it doesn't tell us what's safe to show."""
    pairs, baseline_pairs = results["raw_pairs"], results["raw_baseline_pairs"]

    def _score(agg_model: dict, agg_baseline: dict) -> dict:
        keys = sorted(set(agg_model) | set(agg_baseline))
        m_vals = [agg_model[k] for k in keys]
        b_vals = [agg_baseline[k] for k in keys]
        return {
            "model_mape": _mape(m_vals), "baseline_mape": _mape(b_vals),
            "model_mae": _mae(m_vals), "baseline_mae": _mae(b_vals),
            "n": len(keys),
        }

    # (a) venue-wide total drinks per hour
    venue_hour = _score(_aggregate_sum(pairs, ("hour",)), _aggregate_sum(baseline_pairs, ("hour",)))

    # (b) venue-wide per category per hour — overall across all 6 x 9, plus per-category rows
    cat_hour_model = _aggregate_sum(pairs, ("hour", "category"))
    cat_hour_baseline = _aggregate_sum(baseline_pairs, ("hour", "category"))
    category_overall = _score(cat_hour_model, cat_hour_baseline)
    category_by_cat = {}
    for cat in DRINK_CATEGORIES:
        m = {k: v for k, v in cat_hour_model.items() if k[1] == cat}
        b = {k: v for k, v in cat_hour_baseline.items() if k[1] == cat}
        category_by_cat[cat] = _score(m, b)

    # (c) per-bar total drinks per hour, top 3 bars only
    TOP_BARS = (1, 2, 3)
    bar_hour_model = {k: v for k, v in _aggregate_sum(pairs, ("hour", "bar_rank")).items() if k[1] in TOP_BARS}
    bar_hour_baseline = {k: v for k, v in _aggregate_sum(baseline_pairs, ("hour", "bar_rank")).items() if k[1] in TOP_BARS}
    bar_overall = _score(bar_hour_model, bar_hour_baseline)
    bar_by_rank = {}
    for rank in TOP_BARS:
        m = {k: v for k, v in bar_hour_model.items() if k[1] == rank}
        b = {k: v for k, v in bar_hour_baseline.items() if k[1] == rank}
        bar_by_rank[rank] = _score(m, b)

    return {
        "venue_hour": venue_hour,
        "category_overall": category_overall,
        "category_by_cat": category_by_cat,
        "bar_overall": bar_overall,
        "bar_by_rank": bar_by_rank,
    }


def _print_agg_row(label, s: dict) -> None:
    m_mape = s["model_mape"][0]
    b_mape = s["baseline_mape"][0]
    m_mae = s["model_mae"][0]
    b_mae = s["baseline_mae"][0]
    def _verdict(m, b):
        if np.isnan(m) or np.isnan(b):
            return "n/a"
        return "YES" if m < b else "NO"
    beats_mape = _verdict(m_mape, b_mape)
    beats_mae = _verdict(m_mae, b_mae)
    print(f"    {str(label):>12s}  MAPE: {m_mape:6.1f}% vs {b_mape:6.1f}%  ({beats_mape:>3s})"
          f"   MAE: {m_mae:6.2f} vs {b_mae:6.2f} drinks  ({beats_mae:>3s})   n={s['n']}")


def print_aggregate_report(agg: dict) -> None:
    print("\n" + "=" * 78)
    print("AGGREGATE-LEVEL VALIDATION (Jul-19 holdout) — panel display grains")
    print("=" * 78)
    print("\n  (a) venue-wide total drinks per hour")
    _print_agg_row("all hours", agg["venue_hour"])

    print("\n  (b) venue-wide per category per hour")
    _print_agg_row("overall", agg["category_overall"])
    for cat, s in agg["category_by_cat"].items():
        _print_agg_row(cat, s)

    print("\n  (c) per-bar total drinks per hour (top 3 bars by volume)")
    _print_agg_row("overall", agg["bar_overall"])
    for rank, s in agg["bar_by_rank"].items():
        _print_agg_row(f"rank {rank}", s)


def _print_mape_table(title: str, model_dict: dict, baseline_dict: dict) -> None:
    print(f"\n  {title}")
    keys = sorted(set(model_dict) | set(baseline_dict))
    print(f"    {'key':>10s}  {'model MAPE':>12s}  {'baseline MAPE':>14s}  {'beats baseline':>15s}  n_used/excl")
    for k in keys:
        m_mape, m_n, m_excl = model_dict.get(k, (float('nan'), 0, 0))
        b_mape, b_n, b_excl = baseline_dict.get(k, (float('nan'), 0, 0))
        beats = "YES" if (not np.isnan(m_mape) and not np.isnan(b_mape) and m_mape < b_mape) else (
            "n/a" if np.isnan(m_mape) or np.isnan(b_mape) else "NO")
        print(f"    {str(k):>10s}  {m_mape:11.1f}%  {b_mape:13.1f}%  {beats:>15s}  {m_n}/{m_excl}")


def main() -> None:
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

    sundance14_grid_obj = build_current_grid(sundance14_rows)
    jul19_grid_obj = build_current_grid(jul19_rows)

    print("Sundance 14 actual total:", sundance14_grid_obj.events["total_drinks"].iloc[0])
    print("Jul-19 actual total:", jul19_grid_obj.events["total_drinks"].iloc[0])

    from app.modules.predictions.demand.training_data import build_historical_grid, combine_grids
    hist_tx = pd.read_parquet(
        Path(__file__).parent.parent / "modules/predictions/nowcast/data/training_transactions.parquet"
    )
    hist_grid_obj = build_historical_grid(hist_tx)

    training = combine_grids(hist_grid_obj, sundance14_grid_obj)
    print(f"\nTraining set: {len(training.events)} events (Jul-19 NOT included)")
    print(training.events[["event_id", "source", "total_drinks"]].to_string(index=False))

    predictor = DemandPredictor.from_dataframes(training.events, training.grid)

    results = run_validation(predictor, jul19_grid_obj.grid, sundance14_grid_obj.grid)

    print("\n" + "=" * 70)
    print("VALIDATION: Jul-19 holdout, predicted blind")
    print("=" * 70)
    m_mape, m_n, m_excl = results["overall_model_mape"]
    b_mape, b_n, b_excl = results["overall_baseline_mape"]
    print(f"\nOVERALL MAPE: model = {m_mape:.1f}%  (n={m_n}, excluded_zero_actual={m_excl})")
    print(f"OVERALL MAPE: baseline (Sundance14 same rank/hour) = {b_mape:.1f}%  (n={b_n}, excluded_zero_actual={b_excl})")
    print(f"MODEL BEATS BASELINE OVERALL: {'YES' if m_mape < b_mape else 'NO'}")

    _print_mape_table("By category", results["model_by_category"], results["baseline_by_category"])
    _print_mape_table("By bar rank", results["model_by_bar_rank"], results["baseline_by_bar_rank"])
    _print_mape_table("By hour-of-event (predicting that hour)", results["model_by_hour"], results["baseline_by_hour"])

    print_aggregate_report(aggregate_validation(results))


if __name__ == "__main__":
    main()
