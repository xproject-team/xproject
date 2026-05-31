"""Train Model A (revenue + category demand) on historical Sundance events.

Standalone CLI script. Usage from project root:

    cd backend && source venv/bin/activate
    python -m app.scripts.train_predictions_model

What it does:
  1. Loads cleaned event data via the shared data_loader
     (rain outlier 2025-07-13 is held out by default).
  2. Builds two feature matrices:
       - Revenue:  (hour x bar) -> revenue in EUR
       - Category: (hour x bar) -> unit count per category
  3. Trains two model families per matrix (Ridge + RandomForest),
     keeps whichever scores better under leave-one-event-out CV.
  4. Saves winning artifacts plus a metadata.json sidecar.
  5. Prints a backtest report; non-zero exit if revenue R^2 < 0
     (i.e. the model is worse than predicting the mean).

Phase 2 ML for XProject Sundance 2026. See docs/predictions-module-spec.md.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score

# Import paths assume `python -m app.scripts.train_predictions_model`
# from the backend/ directory.
from app.modules.predictions.data_loader import EventData, load_all_events
from app.modules.predictions.predictors.heuristic import _classify_category

# Category names must match heuristic.py output for train/predict parity.
# Single source of truth: import the category list directly from the
# heuristic predictor so train + predict can never drift.
from app.modules.predictions.predictors.heuristic import (
    CATEGORY_KEYWORDS as _HEURISTIC_CATEGORIES,
)
CATEGORIES: tuple[str, ...] = tuple(_HEURISTIC_CATEGORIES.keys())

# Bar one-hot order locked so train + predict cannot drift.
BAR_NAMES: tuple[str, ...] = ("Cocktail Bar", "Focacceria", "Malandrino")

FEATURE_NAMES: tuple[str, ...] = (
    "hour_of_event",
    "hour_of_day",
    "day_of_week",
    "month",
    "is_weekend",
    "event_total_hours",
    "bar_cocktail_bar",
    "bar_focacceria",
    "bar_malandrino",
)

ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "modules" / "predictions" / "artifacts"


@dataclass(frozen=True)
class BacktestScore:
    """Cross-validation result for one model family on one target."""
    family: str        # "ridge" or "random_forest"
    target: str        # "revenue" or "category:<name>"
    r2: float          # higher is better
    mae: float         # lower is better
    n_train: int
    n_test: int


def _engineer_revenue_features(events: Sequence[EventData]) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """Return (X, y, event_ids) for revenue regression.

    event_ids is a list aligning each row to its source event_date.isoformat()
    so we can do leave-one-event-out CV cleanly.
    """
    rows: list[dict] = []
    event_ids: list[str] = []
    for ev in events:
        if ev.hourly.empty:
            continue
        start = ev.hourly["hour"].min()
        total_hours = int((ev.hourly["hour"].max() - start).total_seconds() // 3600 + 1)
        for _, r in ev.hourly.iterrows():
            ts = r["hour"]
            row = {
                "hour_of_event":     int((ts - start).total_seconds() // 3600),
                "hour_of_day":       ts.hour,
                "day_of_week":       ts.dayofweek,
                "month":             ts.month,
                "is_weekend":        int(ts.dayofweek >= 5),
                "event_total_hours": total_hours,
                "bar_cocktail_bar":  int(r["bar"] == "Cocktail Bar"),
                "bar_focacceria":    int(r["bar"] == "Focacceria"),
                "bar_malandrino":    int(r["bar"] == "Malandrino"),
                "_revenue":          float(r["revenue"]),
            }
            rows.append(row)
            event_ids.append(ev.event_date.date().isoformat())
    df = pd.DataFrame(rows)
    if df.empty:
        return df, pd.Series(dtype=float), []
    y = df.pop("_revenue")
    X = df[list(FEATURE_NAMES)]
    return X, y, event_ids


def _engineer_category_features(events: Sequence[EventData]) -> tuple[pd.DataFrame, dict[str, pd.Series], list[str]]:
    """Return (X, {category: y_series}, event_ids) for category demand.

    For each hour-bar bucket, count units sold per category by parsing
    the comma-separated "products" string from raw orders, classifying
    each product via heuristic._classify_category, then aggregating.
    """
    bucket_records: dict[tuple[str, pd.Timestamp, str], dict] = {}
    event_ids_per_key: dict[tuple[str, pd.Timestamp, str], str] = {}

    for ev in events:
        if ev.raw_orders.empty:
            continue
        start = ev.raw_orders["ts"].dt.floor("h").min()
        total_hours = int((ev.raw_orders["ts"].dt.floor("h").max() - start).total_seconds() // 3600 + 1)
        for _, order in ev.raw_orders.iterrows():
            hour = order["ts"].floor("h")
            bar = order["bar"]
            key = (ev.event_date.date().isoformat(), hour, bar)
            if key not in bucket_records:
                bucket_records[key] = {
                    "hour": hour, "bar": bar, "start": start, "total_hours": total_hours,
                    **{f"cat_{c}": 0 for c in CATEGORIES},
                }
                event_ids_per_key[key] = ev.event_date.date().isoformat()
            products = str(order.get("products", "") or "")
            for p in products.split(","):
                p = p.strip()
                if not p:
                    continue
                cat = _classify_category(p)
                bucket_records[key][f"cat_{cat}"] += 1

    rows: list[dict] = []
    event_ids: list[str] = []
    for key, rec in bucket_records.items():
        ts = rec["hour"]
        start = rec["start"]
        rows.append({
            "hour_of_event":     int((ts - start).total_seconds() // 3600),
            "hour_of_day":       ts.hour,
            "day_of_week":       ts.dayofweek,
            "month":             ts.month,
            "is_weekend":        int(ts.dayofweek >= 5),
            "event_total_hours": rec["total_hours"],
            "bar_cocktail_bar":  int(rec["bar"] == "Cocktail Bar"),
            "bar_focacceria":    int(rec["bar"] == "Focacceria"),
            "bar_malandrino":    int(rec["bar"] == "Malandrino"),
            **{f"cat_{c}": rec[f"cat_{c}"] for c in CATEGORIES},
        })
        event_ids.append(event_ids_per_key[key])
    df = pd.DataFrame(rows)
    if df.empty:
        return df, {c: pd.Series(dtype=float) for c in CATEGORIES}, []
    X = df[list(FEATURE_NAMES)]
    targets = {c: df[f"cat_{c}"].astype(float) for c in CATEGORIES}
    return X, targets, event_ids


def _leave_one_event_out_score(
    X: pd.DataFrame,
    y: pd.Series,
    event_ids: list[str],
    family: str,
    target: str,
) -> BacktestScore:
    """One-out CV: for each event, train on the other 3, predict on it.

    Aggregate y_true vs y_pred across all 4 folds, then score once.
    """
    if X.empty or len(set(event_ids)) < 2:
        return BacktestScore(family=family, target=target, r2=float("nan"),
                             mae=float("nan"), n_train=0, n_test=0)
    eids = np.array(event_ids)
    all_true, all_pred = [], []
    for held_out in sorted(set(event_ids)):
        train_mask = eids != held_out
        test_mask = eids == held_out
        Xtr, ytr = X[train_mask], y[train_mask]
        Xte, yte = X[test_mask], y[test_mask]
        model = _new_model(family)
        model.fit(Xtr, ytr)
        all_true.extend(yte.tolist())
        all_pred.extend(model.predict(Xte).tolist())
    return BacktestScore(
        family=family, target=target,
        r2=r2_score(all_true, all_pred),
        mae=mean_absolute_error(all_true, all_pred),
        n_train=int((eids != list(set(event_ids))[0]).sum()),
        n_test=int((eids == list(set(event_ids))[0]).sum()),
    )


def _new_model(family: str):
    """Factory: identical hyperparameters as used in CV and final fit."""
    if family == "ridge":
        return Ridge(alpha=1.0, random_state=42)
    if family == "random_forest":
        return RandomForestRegressor(n_estimators=100, max_depth=6,
                                     min_samples_leaf=3, random_state=42, n_jobs=1)
    raise ValueError(f"unknown family: {family}")


def main() -> int:
    print("═══ Loading training events (rain held out) ═══")
    events = load_all_events(exclude_outliers=True)
    print(f"  {len(events)} events: {[e.event_date.date().isoformat() for e in events]}")
    if len(events) < 2:
        print("ERROR: need at least 2 events for CV; aborting.")
        return 1

    # ─── Revenue model ───
    print()
    print("═══ Revenue model ═══")
    X, y, eids = _engineer_revenue_features(events)
    print(f"  matrix: {X.shape}, y: {len(y)} (revenue per hour-bar bucket)")
    revenue_scores = [
        _leave_one_event_out_score(X, y, eids, "ridge", "revenue"),
        _leave_one_event_out_score(X, y, eids, "random_forest", "revenue"),
    ]
    for s in revenue_scores:
        print(f"  {s.family:<14s} R^2={s.r2:+.3f}  MAE=EUR {s.mae:>7.2f}")
    revenue_winner = max(revenue_scores, key=lambda s: (0 if np.isnan(s.r2) else s.r2))
    print(f"  WINNER: {revenue_winner.family}")
    revenue_model = _new_model(revenue_winner.family)
    revenue_model.fit(X, y)

    # ─── Category model (one per category) ───
    print()
    print("═══ Category models (one per category) ═══")
    X2, targets, eids2 = _engineer_category_features(events)
    print(f"  matrix: {X2.shape}, {len(targets)} categories")
    category_winners: dict[str, str] = {}
    category_models: dict[str, object] = {}
    category_scores: list[BacktestScore] = []
    for cat, yc in targets.items():
        if yc.sum() == 0:
            print(f"  {cat:<10s} skipped (zero units in training data)")
            continue
        scores = [
            _leave_one_event_out_score(X2, yc, eids2, "ridge", f"category:{cat}"),
            _leave_one_event_out_score(X2, yc, eids2, "random_forest", f"category:{cat}"),
        ]
        category_scores.extend(scores)
        winner = max(scores, key=lambda s: (0 if np.isnan(s.r2) else s.r2))
        category_winners[cat] = winner.family
        m = _new_model(winner.family)
        m.fit(X2, yc)
        category_models[cat] = m
        print(f"  {cat:<10s}  winner={winner.family:<14s}  R^2={winner.r2:+.3f}  MAE={winner.mae:>6.2f} units")

    # ─── Save artifacts ───
    print()
    print("═══ Saving artifacts ═══")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    revenue_path = ARTIFACT_DIR / "model_a_revenue.joblib"
    category_path = ARTIFACT_DIR / "model_a_category.joblib"
    metadata_path = ARTIFACT_DIR / "metadata.json"

    joblib.dump({"model": revenue_model, "family": revenue_winner.family,
                 "feature_names": list(FEATURE_NAMES)}, revenue_path)
    joblib.dump({"models": category_models, "winners": category_winners,
                 "feature_names": list(FEATURE_NAMES),
                 "categories": list(CATEGORIES)}, category_path)
    metadata = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_events": [e.event_date.date().isoformat() for e in events],
        "n_training_events": len(events),
        "feature_names": list(FEATURE_NAMES),
        "categories": list(CATEGORIES),
        "revenue": {
            "winner": revenue_winner.family,
            "r2": revenue_winner.r2,
            "mae_eur": revenue_winner.mae,
            "all_scores": [s.__dict__ for s in revenue_scores],
        },
        "category": {
            "winners": category_winners,
            "all_scores": [s.__dict__ for s in category_scores],
        },
    }
    metadata_path.write_text(json.dumps(metadata, indent=2))

    print(f"  {revenue_path}")
    print(f"  {category_path}")
    print(f"  {metadata_path}")

    # ─── Gate: refuse to save if revenue R^2 is negative ───
    if revenue_winner.r2 < 0 or np.isnan(revenue_winner.r2):
        print()
        print(f"⚠️  Revenue R^2 = {revenue_winner.r2:.3f} (worse than mean baseline)")
        print("    Artifacts saved but MLPredictor.is_ready should stay False.")
        return 2

    print()
    print(f"✅ Training complete. Revenue R^2 = {revenue_winner.r2:+.3f}, MAE EUR {revenue_winner.mae:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
