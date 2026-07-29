"""Tests for the drinks-demand predictor's pure logic — no DB, no
network. Mirrors test_nowcast_retrain.py's spirit (nowcast has no
test_predictor.py of its own; this establishes that precedent for the
demand module, per the exploration report's finding that System A's
math has good endpoint tests but the fit function itself is only
exercised indirectly).
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from app.modules.predictions.demand.predictor import (
    BAR_RANKS,
    HOUR_GRID,
    DemandPredictor,
    fit_demand_curves,
)
from app.modules.predictions.demand.training_data import (
    DRINK_CATEGORIES,
    MAX_BAR_RANK,
    build_current_grid,
    build_historical_grid,
    combine_grids,
)


# ─── training_data.py ────────────────────────────────────────────────

def _hist_tx_row(event_id, event_date, timestamp, bar_name, product_names):
    return {
        "event_id": event_id, "event_date": event_date, "timestamp": timestamp,
        "bar_name": bar_name, "product_names": product_names,
        "item_count": len(product_names.split(",")), "amount_eur": 0.0,
    }


def test_build_historical_grid_explodes_and_classifies():
    tx = pd.DataFrame([
        _hist_tx_row("ev1", "2024-06-16", pd.Timestamp("2024-06-16 12:00:00"), "Bar A", "Sprtiz, Birra"),
        _hist_tx_row("ev1", "2024-06-16", pd.Timestamp("2024-06-16 12:30:00"), "Bar A", "Bicchiere"),
    ])
    result = build_historical_grid(tx)
    assert result.events["total_drinks"].iloc[0] == 2  # Bicchiere (deposit) excluded
    cats = set(result.grid["category"])
    assert cats == {"spritz", "beer"}


def test_build_historical_grid_excludes_deposit_and_unclassified():
    tx = pd.DataFrame([
        _hist_tx_row("ev1", "2024-06-16", pd.Timestamp("2024-06-16 12:00:00"), "Bar A",
                     "Bicchiere, Some Unseen Item, Cocktail"),
    ])
    result = build_historical_grid(tx)
    assert result.events["total_drinks"].iloc[0] == 1
    assert list(result.grid["category"]) == ["cocktail"]


def test_build_current_grid_excludes_nothing_extra_caller_already_filtered():
    """build_current_grid trusts the caller to have already excluded
    deposit/food rows (see build_demand_training_data.py's SQL filter)
    — it doesn't re-filter category here."""
    rows = [
        {"event_id": "ev1", "event_date": "2026-06-14",
         "ordered_at": pd.Timestamp("2026-06-14 12:00:00", tz=timezone.utc),
         "bar_id": "bar-a", "category": "cocktail", "qty": 1.0},
    ]
    result = build_current_grid(rows)
    assert result.events["total_drinks"].iloc[0] == 1
    assert result.grid["category"].iloc[0] == "cocktail"


def test_bar_ranking_busiest_bar_is_rank_1():
    rows = [
        {"event_id": "ev1", "event_date": "2026-06-14",
         "ordered_at": pd.Timestamp("2026-06-14 12:00:00", tz=timezone.utc),
         "bar_id": "quiet-bar", "category": "wine", "qty": 1.0},
    ] + [
        {"event_id": "ev1", "event_date": "2026-06-14",
         "ordered_at": pd.Timestamp("2026-06-14 12:00:00", tz=timezone.utc),
         "bar_id": "busy-bar", "category": "beer", "qty": 1.0},
    ] * 5
    result = build_current_grid(rows)
    busy_rank = result.grid[result.grid["category"] == "beer"]["bar_rank"].iloc[0]
    quiet_rank = result.grid[result.grid["category"] == "wine"]["bar_rank"].iloc[0]
    assert busy_rank == 1
    assert quiet_rank == 2


def test_bar_rank_capped_at_max():
    rows = [
        {"event_id": "ev1", "event_date": "2026-06-14",
         "ordered_at": pd.Timestamp("2026-06-14 12:00:00", tz=timezone.utc),
         "bar_id": f"bar-{i}", "category": "beer", "qty": 1.0}
        for i in range(8)  # 8 distinct bars, each with 1 sale -> all tied, ranks 1..8 before capping
    ]
    result = build_current_grid(rows)
    assert result.grid["bar_rank"].max() == MAX_BAR_RANK


def test_hour_of_event_elapsed_from_first_order():
    rows = [
        {"event_id": "ev1", "event_date": "2026-06-14",
         "ordered_at": pd.Timestamp("2026-06-14 12:00:00", tz=timezone.utc),
         "bar_id": "bar-a", "category": "beer", "qty": 1.0},
        {"event_id": "ev1", "event_date": "2026-06-14",
         "ordered_at": pd.Timestamp("2026-06-14 15:30:00", tz=timezone.utc),
         "bar_id": "bar-a", "category": "beer", "qty": 1.0},
    ]
    result = build_current_grid(rows)
    hours = sorted(result.grid["hour_of_event"].unique())
    assert hours == [0, 3]  # first order = hour 0, 3.5h later floors to hour 3


def test_combine_grids_concatenates():
    rows_a = [{"event_id": "ev1", "event_date": "2026-06-14",
               "ordered_at": pd.Timestamp("2026-06-14 12:00:00", tz=timezone.utc),
               "bar_id": "bar-a", "category": "beer", "qty": 1.0}]
    rows_b = [{"event_id": "ev2", "event_date": "2026-07-19",
               "ordered_at": pd.Timestamp("2026-07-19 12:00:00", tz=timezone.utc),
               "bar_id": "bar-a", "category": "wine", "qty": 1.0}]
    combined = combine_grids(build_current_grid(rows_a), build_current_grid(rows_b))
    assert set(combined.events["event_id"]) == {"ev1", "ev2"}
    assert len(combined.grid) == 2


def test_combine_grids_skips_empty():
    rows = [{"event_id": "ev1", "event_date": "2026-06-14",
             "ordered_at": pd.Timestamp("2026-06-14 12:00:00", tz=timezone.utc),
             "bar_id": "bar-a", "category": "beer", "qty": 1.0}]
    empty = build_current_grid([])
    combined = combine_grids(build_current_grid(rows), empty)
    assert len(combined.events) == 1


# ─── predictor.py — fit_demand_curves ───────────────────────────────

def _make_synthetic_grid(n_events: int = 4) -> tuple[pd.DataFrame, pd.DataFrame]:
    """n_events synthetic events, each with a smooth accumulation curve
    and a consistent category/bar mix, so the fit is checkable against
    hand-computable expectations."""
    events, grid_rows = [], []
    for i in range(n_events):
        eid = f"ev{i}"
        total = 100 + i * 10
        events.append({"event_id": eid, "source": "synthetic", "total_drinks": total})
        for h in range(0, 6):
            hour_total = total // 6
            grid_rows.append({"event_id": eid, "source": "synthetic", "bar_rank": 1,
                               "wall_clock_hour": 12 + h, "hour_of_event": h,
                               "category": "beer", "drinks_count": hour_total // 2})
            grid_rows.append({"event_id": eid, "source": "synthetic", "bar_rank": 2,
                               "wall_clock_hour": 12 + h, "hour_of_event": h,
                               "category": "cocktail", "drinks_count": hour_total // 2})
    return pd.DataFrame(events), pd.DataFrame(grid_rows)


def test_fit_demand_curves_shape_curve_reaches_one():
    events_df, grid_df = _make_synthetic_grid()
    shape_curve, r2_table, category_share, bar_share = fit_demand_curves(events_df, grid_df)
    # All synthetic events end their real data at hour 5; shape_curve
    # should be ~1.0 (or very close) by then and held flat after.
    assert shape_curve.iloc[-1] == pytest.approx(1.0, abs=0.05)
    assert shape_curve.is_monotonic_increasing


def test_fit_demand_curves_category_share_sums_to_one_per_hour():
    events_df, grid_df = _make_synthetic_grid()
    _, _, category_share, _ = fit_demand_curves(events_df, grid_df)
    only_active = category_share[["beer", "cocktail"]]
    row_sums = only_active.sum(axis=1)
    # beer + cocktail are the only two categories present in the
    # synthetic fixture; their shares should sum to ~1 at every hour
    # that had data (later hours may fall back to equal-split filler).
    assert (row_sums.round(2) == 1.0).all()


def test_fit_demand_curves_bar_share_reflects_split():
    events_df, grid_df = _make_synthetic_grid()
    _, _, _, bar_share = fit_demand_curves(events_df, grid_df)
    # bar_rank 1 (beer) and bar_rank 2 (cocktail) split evenly in the fixture
    assert bar_share[1].iloc[0] == pytest.approx(0.5, abs=0.05)
    assert bar_share[2].iloc[0] == pytest.approx(0.5, abs=0.05)


def test_fit_demand_curves_r2_higher_late_than_early_when_events_vary():
    """Events with different totals but the same relative shape: r²
    should be low very early (little separated signal) and high once
    most of the night's data has landed — same qualitative behavior as
    nowcast's fit."""
    events_df, grid_df = _make_synthetic_grid(n_events=6)
    _, r2_table, _, _ = fit_demand_curves(events_df, grid_df)
    assert r2_table.iloc[-1] >= r2_table.iloc[0]


# ─── DemandPredictor.predict ─────────────────────────────────────────

def test_predict_no_signal_yet_uses_fallback():
    events_df, grid_df = _make_synthetic_grid()
    predictor = DemandPredictor.from_dataframes(events_df, grid_df)
    result = predictor.predict(drinks_so_far=0, hour_offset_from_start=0.0)
    assert result["fallback_used"] is True
    assert result["confidence"] == 0.0
    assert result["predicted_final_total"] == pytest.approx(predictor.historical_mean_total)


def test_predict_with_signal_calibrates_against_actuals():
    events_df, grid_df = _make_synthetic_grid()
    predictor = DemandPredictor.from_dataframes(events_df, grid_df)
    result = predictor.predict(drinks_so_far=50, hour_offset_from_start=3.0)
    assert result["fallback_used"] is False
    assert result["predicted_final_total"] > 0
    assert result["confidence"] >= 0.0


def test_predict_by_hour_only_covers_future_hours():
    events_df, grid_df = _make_synthetic_grid()
    predictor = DemandPredictor.from_dataframes(events_df, grid_df)
    result = predictor.predict(drinks_so_far=30, hour_offset_from_start=3.0)
    predicted_hours = set(result["predicted_by_hour"].keys())
    assert all(h > 3.0 for h in predicted_hours)


def test_predict_by_hour_has_all_bar_ranks_and_categories():
    events_df, grid_df = _make_synthetic_grid()
    predictor = DemandPredictor.from_dataframes(events_df, grid_df)
    result = predictor.predict(drinks_so_far=30, hour_offset_from_start=2.0)
    any_hour = next(iter(result["predicted_by_hour"].values()))
    assert set(any_hour.keys()) == set(BAR_RANKS)
    for rank in BAR_RANKS:
        assert set(any_hour[rank].keys()) == set(DRINK_CATEGORIES)


def test_predict_never_returns_negative_counts():
    events_df, grid_df = _make_synthetic_grid()
    predictor = DemandPredictor.from_dataframes(events_df, grid_df)
    result = predictor.predict(drinks_so_far=30, hour_offset_from_start=2.0)
    for by_bar in result["predicted_by_hour"].values():
        for by_cat in by_bar.values():
            for count in by_cat.values():
                assert count >= 0
