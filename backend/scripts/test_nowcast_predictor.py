#!/usr/bin/env python3
"""test_nowcast_predictor.py — leave-one-out back-test for NowcastPredictor.

For each of the 9 historical events, fit a NowcastPredictor on the
OTHER 8 events only (so the target event's own shape never leaks into
what it's being predicted from), then simulate calling predict() at
hour offsets 2, 4, 6, 8 during the target event using that event's own
real partial revenue up to that hour. Compare predicted_final vs the
event's real actual_final.

Not a pytest suite — a diagnostic script, run directly (from backend/,
so the app package resolves on sys.path):
    PYTHONPATH=. venv/bin/python scripts/test_nowcast_predictor.py

Phase D moved the predictor itself into
app/modules/predictions/nowcast/predictor.py (now backed by a process
singleton + parquet shipped alongside the module). This script now
imports from there instead of the old backend/scripts/nowcast_predictor.py
(deleted — superseded by the move).

Phase F ("old vs new" comparison): Phase F set out to add year-
segmented shape curves, hour-of-day weighting, a first-hour booster,
and per-year confidence recalibration. All four were built and
back-tested — every one made MAPE WORSE at every hour checkpoint (see
predictor.py's module docstring, "Phase F — what shipped and what
didn't", for the actual numbers). All four were reverted; shape_curve
and r2_table are byte-for-byte the same computation as Phase C/D. So
the h2/h4/h6/h8 MAPE below is IDENTICAL to Phase C's original
back-test — that's not a bug in this script, it's the honest result of
reverting changes that didn't help. The one Phase F change that DID
ship — a year-weighted fallback mean, used only pre-event / before any
revenue lands — is compared separately below (OLD_FALLBACK_MODE
section), since it doesn't touch the h2-h8 code path at all.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.modules.predictions.nowcast.predictor import (
    NowcastPredictor,
    DATA_DIR as DEFAULT_PARQUET_DIR,
    year_weighted_fallback_mean,
)

BACKTEST_HOURS = [2, 4, 6, 8]


def load_data(parquet_dir: Path = DEFAULT_PARQUET_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    events_df = pd.read_parquet(parquet_dir / "training_events.parquet")
    transactions_df = pd.read_parquet(parquet_dir / "training_transactions.parquet")
    return events_df, transactions_df


def revenue_so_far(tx_event: pd.DataFrame, first_tx_time, hour: float) -> float:
    elapsed = (tx_event["timestamp"] - first_tx_time).dt.total_seconds() / 3600.0
    return float(tx_event.loc[elapsed <= hour, "amount_eur"].sum())


def run_backtest() -> pd.DataFrame:
    events_df, transactions_df = load_data()
    event_ids = events_df["event_id"].tolist()

    rows = []
    for target_id in event_ids:
        train_events = events_df[events_df["event_id"] != target_id].reset_index(drop=True)
        train_tx = transactions_df[transactions_df["event_id"] != target_id].reset_index(drop=True)
        predictor = NowcastPredictor.from_dataframes(train_events, train_tx)

        target_row = events_df[events_df["event_id"] == target_id].iloc[0]
        actual_final = float(target_row["total_revenue"])
        first_tx_time = target_row["first_tx_time"]
        tx_target = transactions_df[transactions_df["event_id"] == target_id]

        target_year = int(pd.to_datetime(target_row["event_date"]).year)

        for hour in BACKTEST_HOURS:
            current_rev = revenue_so_far(tx_target, first_tx_time, hour)
            result = predictor.predict(current_rev, hour, target_year=target_year)
            predicted_final = result["predicted_final_revenue_eur"]
            signed_err = predicted_final - actual_final
            abs_err = abs(signed_err)
            abs_pct_err = abs_err / actual_final if actual_final else float("nan")
            signed_pct_err = signed_err / actual_final if actual_final else float("nan")

            rows.append({
                "event_id": target_id,
                "event_date": target_row["event_date"],
                "hour": hour,
                "current_revenue_so_far": round(current_rev, 2),
                "actual_final": actual_final,
                "predicted_final": predicted_final,
                "confidence": result["confidence"],
                "abs_error_eur": round(abs_err, 2),
                "abs_pct_error": round(abs_pct_err * 100, 2),
                "signed_pct_error": round(signed_pct_err * 100, 2),
            })

    return pd.DataFrame(rows)


def compare_fallback_means() -> pd.DataFrame:
    """The one Phase F change that shipped: OLD (Phase C/D) fallback =
    flat all-time mean, regardless of target year. NEW (Phase F)
    fallback = year_weighted_fallback_mean(target_year) — most recent
    2 years at/before target_year, newest weighted 2x. Doesn't touch
    the h2-h8 code path (see module docstring) — reported separately.
    """
    events_df, _ = load_data()
    old_flat_mean = float(events_df["total_revenue"].mean())
    rows = []
    for target_year in [2024, 2025, 2026, 2027]:
        new_mean = year_weighted_fallback_mean(events_df, target_year)
        rows.append({
            "target_year": target_year,
            "old_flat_mean": round(old_flat_mean, 0),
            "new_year_weighted_mean": round(new_mean, 0),
            "delta": round(new_mean - old_flat_mean, 0),
        })
    return pd.DataFrame(rows)


def main() -> int:
    results = run_backtest()

    print("# NowcastPredictor back-test (leave-one-out, 9 historical events)\n")

    print("## RMSE and MAPE by hour offset — OLD (Phase C/D) vs NEW (Phase F)\n")
    print(
        "Identical by design: Phase F's year-segmented shape_curve, hour-of-day\n"
        "weighting, first-hour booster, and per-year r2_table all made back-test\n"
        "MAPE WORSE at every hour (see predictor.py's \"Phase F — what shipped and\n"
        "what didn't\" docstring for the numbers) and were reverted. The h2-h8\n"
        "code path below is byte-for-byte the same computation as Phase C/D.\n"
    )
    print("| hour | RMSE (EUR) | Mean Abs % Error (OLD == NEW) | mean confidence |")
    print("|---|---|---|---|")
    for hour in BACKTEST_HOURS:
        sub = results[results["hour"] == hour]
        rmse = np.sqrt((sub["abs_error_eur"] ** 2).mean())
        mape = sub["abs_pct_error"].mean()
        mean_conf = sub["confidence"].mean()
        print(f"| {hour} | €{rmse:,.0f} | {mape:.1f}% | {mean_conf:.3f} |")

    print("\n## Fallback mean — OLD (flat) vs NEW (year-weighted) — the one Phase F change that shipped\n")
    fallback_cmp = compare_fallback_means()
    print("| target_year | old_flat_mean | new_year_weighted_mean | delta |")
    print("|---|---|---|---|")
    for _, r in fallback_cmp.iterrows():
        print(f"| {int(r.target_year)} | €{r.old_flat_mean:,.0f} | €{r.new_year_weighted_mean:,.0f} | €{r.delta:+,.0f} |")

    print("\n## Per-event: actual vs predicted at each hour\n")
    print("| event_date | actual_final | h=2 pred (err%) | h=4 pred (err%) | "
          "h=6 pred (err%) | h=8 pred (err%) |")
    print("|---|---|---|---|---|---|")
    for eid, g in results.groupby("event_id", sort=False):
        g = g.set_index("hour")
        event_date = g["event_date"].iloc[0]
        actual = g["actual_final"].iloc[0]
        cells = []
        for hour in BACKTEST_HOURS:
            r = g.loc[hour]
            cells.append(f"€{r['predicted_final']:,.0f} ({r['signed_pct_error']:+.1f}%)")
        print(f"| {event_date} | €{actual:,.0f} | " + " | ".join(cells) + " |")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
