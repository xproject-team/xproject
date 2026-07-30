"""predictor.py — the drinks-demand forecaster.

Directly mirrors app/modules/predictions/nowcast/predictor.py's method
(historical shape curve, normalized by each event's own final total,
real-time calibration by dividing actuals-so-far by the curve's value
at that hour, r²-based confidence) — same math, same
"Do not ship a more sophisticated model that performs worse than the
simple one" discipline Phase F already proved out for this exact
small-n regime (9-10 events). Extended for two more dimensions
(bar, category) via an INDEPENDENT-factors decomposition rather than a
true joint (bar, category, hour) curve, because a joint curve would
fragment 9-10 events across 5 bar-ranks x 6 categories x 11 hours =
330 cells — Phase F's own back-tested warning against over-segmenting
applies even harder here than it did to nowcast's single extra
dimension (year). See training_data.py for how the grid is built.

─── Method ──────────────────────────────────────────────────────────
1. overall shape_curve[h] = mean, across training events, of
   (cumulative drinks through hour_of_event h) / (event's final total
   drinks). r2_table[h] = Pearson r² of (cumulative drinks at h) vs
   (final total), across events — identical to nowcast.
2. category_share[cat][h] = mean, across events, of (drinks in
   category cat during hour h) / (total drinks during hour h) — the
   TYPICAL category mix at that point in the night, hour-local (not
   cumulative — the mix shifts through the night, e.g. more wine
   early, more spritz/cocktails later; a cumulative share would blur
   that shift).
3. bar_share[rank][h] = same pattern, for the Nth-busiest bar (by
   total event volume) instead of category. Bar identity does not
   transfer across events — see training_data.py — so this is
   learned per RANK position, not per bar name.
4. At predict time: calibrate the OVERALL total exactly like nowcast
   (actual_so_far / shape_curve[hour]), then split each future hour's
   predicted incremental volume by category_share x bar_share
   (independent factors — see above). category_share and bar_share
   themselves are NOT real-time-calibrated in this version; only the
   overall total is, mirroring the one thing nowcast itself
   calibrates. Confidence is the overall r² at that hour, applied to
   every (bar, category) cell it produces — a per-cell r² would be
   exactly the over-segmentation Phase F warned against.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.modules.predictions.demand.training_data import DRINK_CATEGORIES, MAX_BAR_RANK

HOUR_GRID = np.arange(0, 11, 1.0)  # elapsed hours since first order: 0..10, matches nowcast
DATA_DIR = Path(__file__).parent / "data"
BAR_RANKS = tuple(range(1, MAX_BAR_RANK + 1))

# Bump whenever a change to this module would make an OLD pickled
# bundle unsafe to load into the CURRENT DemandPredictor (a renamed/
# removed field, a changed meaning for an existing one, etc.). retrain.py
# stamps every new bundle with this; from_bundle() refuses to load a
# bundle whose stamp doesn't match, loudly (a named exception with a
# clear message), rather than silently deserializing into a
# wrong/partial predictor. See loader.py for how that surfaces to callers.
FORMAT_VERSION = 1


class IncompatibleArtifactFormatError(Exception):
    """Raised by DemandPredictor.from_bundle when the bundle's
    format_version doesn't match this code's FORMAT_VERSION. The
    artifact must be retrained, not loaded — see FORMAT_VERSION."""


def fit_demand_curves(
    events_df: pd.DataFrame, grid_df: pd.DataFrame, weights: pd.Series | None = None,
    shape_only: pd.DataFrame | None = None,
) -> tuple[pd.Series, pd.Series, pd.DataFrame, pd.DataFrame]:
    """Fit shape_curve, r2_table (both indexed by HOUR_GRID, exactly
    like nowcast), category_share (DataFrame: rows=HOUR_GRID,
    cols=DRINK_CATEGORIES), bar_share (DataFrame: rows=HOUR_GRID,
    cols=BAR_RANKS). A free function, not a method, for the same
    leave-one-out back-testing reason as nowcast's fit_shape_and_r2.

    weights: optional Series indexed by event_id, defaulting to 1.0 for
    every event when omitted (the original unweighted behavior). Lets a
    caller up-weight events closer to the target configuration (e.g.
    current-season vs. 2024/2025 historical) in all three pooled
    averages. Only apply a non-uniform scheme after confirming via
    leave-one-out back-testing that it actually reduces error — see
    retrain.py's module docstring for the Day-3-closeout finding.

    shape_only: optional DataFrame with columns [event_id, hour_of_event,
    count] — per-hour proxy counts for events whose PER-LINE category/bar
    detail is not trustworthy enough to enter category_share/bar_share,
    but whose per-ORDER counts are complete enough to inform the overall
    shape_curve/r2 (section 1 only). Built for Jul-5: its per-line data
    has non-random per-bar gaps (2 bars at 0% coverage — see the Day 3
    exclusion decision), but event_orders.confirmed_line_count is
    populated for all 4,133 orders including the 880 with no matching
    customer_purchases line, so the cumulative-shape signal survives even
    though the category/bar breakdown doesn't. These events never appear
    in events_df/grid_df — they are pure shape-curve contributors.
    """
    totals = events_df.set_index("event_id")["total_drinks"]
    if weights is None:
        weights = pd.Series(1.0, index=totals.index)

    # ── 1. Overall shape curve + r² (exact nowcast pattern) ──────────
    per_event_hourly = (
        grid_df.groupby(["event_id", "hour_of_event"])["drinks_count"].sum().reset_index()
    )
    matrix: dict[str, np.ndarray] = {}
    for eid, g in per_event_hourly.groupby("event_id"):
        g = g.sort_values("hour_of_event")
        x = g["hour_of_event"].to_numpy(dtype=float)
        y = g["drinks_count"].cumsum().to_numpy(dtype=float)
        matrix[eid] = np.interp(HOUR_GRID, x, y, left=0.0, right=totals[eid])

    if shape_only is not None and not shape_only.empty:
        shape_only_totals = shape_only.groupby("event_id")["count"].sum()
        for eid, g in shape_only.groupby("event_id"):
            g = g.sort_values("hour_of_event")
            x = g["hour_of_event"].to_numpy(dtype=float)
            y = g["count"].cumsum().to_numpy(dtype=float)
            matrix[eid] = np.interp(HOUR_GRID, x, y, left=0.0, right=shape_only_totals[eid])
        totals = pd.concat([totals, shape_only_totals])

    matrix_df = pd.DataFrame(matrix, index=HOUR_GRID).T

    finals = totals.reindex(matrix_df.index)
    w = weights.reindex(finals.index).fillna(1.0)
    normalized = matrix_df.div(finals, axis=0)
    shape_curve = normalized.mul(w, axis=0).sum(axis=0) / w.sum()

    r2_values = {}
    for hr in HOUR_GRID:
        col = matrix_df[hr]
        if col.std() == 0 or finals.std() == 0:
            r2_values[hr] = 0.0
        else:
            r2_values[hr] = float(_weighted_r2(col.to_numpy(), finals.to_numpy(), w.to_numpy()))
    r2_table = pd.Series(r2_values)

    # ── 2. Category share by hour (hour-local, not cumulative) ───────
    hourly_totals = grid_df.groupby(["event_id", "hour_of_event"])["drinks_count"].sum()
    cat_hourly = grid_df.groupby(["event_id", "hour_of_event", "category"])["drinks_count"].sum()

    cat_share_rows = []
    for (eid, h), total_h in hourly_totals.items():
        if total_h <= 0:
            continue
        for cat in DRINK_CATEGORIES:
            cnt = cat_hourly.get((eid, h, cat), 0)
            cat_share_rows.append({"event_id": eid, "hour_of_event": h, "category": cat,
                                    "share": cnt / total_h, "weight": weights.get(eid, 1.0)})
    cat_share_df = pd.DataFrame(cat_share_rows)
    category_share = _weighted_share_table(cat_share_df, "category", DRINK_CATEGORIES)
    # Interpolate/ffill small gaps (an hour with zero events reporting
    # any drinks at all) rather than leaving NaN, then fall back to a
    # flat equal split only where truly nothing was ever observed.
    category_share = category_share.interpolate(limit_direction="both")
    category_share = category_share.fillna(1.0 / len(DRINK_CATEGORIES))

    # ── 3. Bar-rank share by hour (same pattern) ──────────────────────
    bar_hourly = grid_df.groupby(["event_id", "hour_of_event", "bar_rank"])["drinks_count"].sum()
    bar_share_rows = []
    for (eid, h), total_h in hourly_totals.items():
        if total_h <= 0:
            continue
        for rank in BAR_RANKS:
            cnt = bar_hourly.get((eid, h, rank), 0)
            bar_share_rows.append({"event_id": eid, "hour_of_event": h, "bar_rank": rank,
                                    "share": cnt / total_h, "weight": weights.get(eid, 1.0)})
    bar_share_df = pd.DataFrame(bar_share_rows)
    bar_share = _weighted_share_table(bar_share_df, "bar_rank", list(BAR_RANKS))
    bar_share = bar_share.interpolate(limit_direction="both")
    bar_share = bar_share.fillna(1.0 / len(BAR_RANKS))

    return shape_curve, r2_table, category_share, bar_share


def _weighted_r2(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    """Weighted Pearson r², reducing to np.corrcoef(x, y)[0,1]**2 when
    every weight is equal (the unweighted call site's original math)."""
    wx = np.average(x, weights=w)
    wy = np.average(y, weights=w)
    cov = np.average((x - wx) * (y - wy), weights=w)
    varx = np.average((x - wx) ** 2, weights=w)
    vary = np.average((y - wy) ** 2, weights=w)
    if varx <= 0 or vary <= 0:
        return 0.0
    r = cov / np.sqrt(varx * vary)
    return float(r ** 2)


def _weighted_share_table(share_rows_df: pd.DataFrame, col_key: str, columns: list) -> pd.DataFrame:
    """Weighted mean of `share` grouped by (hour_of_event, col_key), using
    the per-row `weight` column. Reduces to a plain mean when all weights
    are equal — same shape/index contract as the original .mean() call."""
    if share_rows_df.empty:
        return pd.DataFrame(index=HOUR_GRID, columns=columns, dtype=float)
    share_rows_df = share_rows_df.assign(_wshare=share_rows_df["share"] * share_rows_df["weight"])
    grouped = share_rows_df.groupby(["hour_of_event", col_key])
    weighted_mean = grouped["_wshare"].sum() / grouped["weight"].sum()
    return weighted_mean.unstack(col_key).reindex(index=HOUR_GRID, columns=columns)


def fit_interval_table(
    events_df: pd.DataFrame, grid_df: pd.DataFrame, weights: pd.Series | None = None,
    shape_only: pd.DataFrame | None = None,
) -> pd.Series:
    """Leave-one-out half-width table for the predicted_final_total
    confidence band, indexed by HOUR_GRID. half_width[h] = mean absolute
    relative error of predicted_final_total, across LOO folds, when the
    prediction is made h hours into the event — same indexing/semantics
    as r2_table (compares a prediction made at hour h against the
    event's true final total), just expressed as an error magnitude
    instead of a variance-explained fraction. Widens at low-r2/early
    hours for the same underlying reason: little cumulative signal yet.

    Expensive (refits once per held-out training event) — call once at
    retrain time and persist the result; DemandPredictor never computes
    this implicitly (see interval_table param on from_dataframes/predict).
    """
    totals = events_df.set_index("event_id")["total_drinks"]
    event_ids = events_df["event_id"].unique().tolist()
    errors_by_hour: dict[float, list[float]] = {float(h): [] for h in HOUR_GRID}

    for held_out in event_ids:
        actual_final = float(totals[held_out])
        if actual_final <= 0:
            continue
        train_events = events_df[events_df["event_id"] != held_out]
        train_grid = grid_df[grid_df["event_id"] != held_out]
        held_out_grid = grid_df[grid_df["event_id"] == held_out]
        if train_events.empty:
            continue
        fold_predictor = DemandPredictor.from_dataframes(train_events, train_grid, weights, shape_only)
        for h in HOUR_GRID:
            observed_so_far = held_out_grid[held_out_grid["hour_of_event"] <= h]["drinks_count"].sum()
            prediction = fold_predictor.predict(float(observed_so_far), float(h))
            predicted_final = prediction["predicted_final_total"]
            errors_by_hour[float(h)].append(abs(actual_final - predicted_final) / actual_final)

    half_width = {h: (float(np.mean(errs)) if errs else float("nan")) for h, errs in errors_by_hour.items()}
    table = pd.Series(half_width).reindex(HOUR_GRID)
    return table.interpolate(limit_direction="both")


# Day 4 "hot night" manual toggle (events.hot_night_override — see
# alembic migration ae1). Jul-19 (the only >=33C event observed so far)
# showed spritz at 27-36% actual share during hours 1-5 vs. this
# model's pooled ~15-18% expectation — a +12 to +19 percentage-point
# gap. One hot event isn't enough to fit that as a weather feature
# responsibly (Day 3 closeout report), so this is a fixed, manually
# toggled boost using the midpoint of the observed gap, not a fitted
# parameter. Applied ONLY to hours 1-5, ONLY to spritz share; every
# other category's share is scaled down proportionally so shares still
# sum to 1. Never applied automatically — see loader.py / router.
HOT_NIGHT_SPRITZ_BOOST_PP = 0.15
HOT_NIGHT_HOURS = frozenset({1.0, 2.0, 3.0, 4.0, 5.0})


def apply_hot_night_boost(category_fracs: dict[str, float], hour: float) -> dict[str, float]:
    """Return category_fracs with spritz boosted and the rest scaled
    down proportionally, for hours 1-5 only. Outside that window, or if
    spritz is already at/above 1.0 (never happens in practice, guarded
    anyway), returns category_fracs unchanged."""
    if hour not in HOT_NIGHT_HOURS:
        return category_fracs
    old_spritz = category_fracs.get("spritz", 0.0)
    new_spritz = min(1.0, old_spritz + HOT_NIGHT_SPRITZ_BOOST_PP)
    boost_applied = new_spritz - old_spritz
    others_total = sum(v for k, v in category_fracs.items() if k != "spritz")
    if boost_applied <= 0 or others_total <= 0:
        return category_fracs
    shrink_factor = max(0.0, (others_total - boost_applied) / others_total)
    return {
        k: (new_spritz if k == "spritz" else v * shrink_factor)
        for k, v in category_fracs.items()
    }


class DemandPredictor:
    """Stateless-per-call, mirrors NowcastPredictor's lifecycle exactly
    (fit once at construction from parquet or from_dataframes, predict()
    any number of times, never mutates)."""

    def __init__(self, data_dir: str | Path = DATA_DIR, suffix: str = "") -> None:
        self.data_dir = Path(data_dir)
        events_df, grid_df = self._load_parquet(self.data_dir, suffix)
        self._fit_from(events_df, grid_df)

    @staticmethod
    def _load_parquet(data_dir: Path, suffix: str = "") -> tuple[pd.DataFrame, pd.DataFrame]:
        events_df = pd.read_parquet(data_dir / f"training_events{suffix}.parquet")
        grid_df = pd.read_parquet(data_dir / f"training_grid{suffix}.parquet")
        return events_df, grid_df

    @classmethod
    def from_dataframes(
        cls, events_df: pd.DataFrame, grid_df: pd.DataFrame, weights: pd.Series | None = None,
        shape_only: pd.DataFrame | None = None, interval_table: pd.Series | None = None,
    ) -> "DemandPredictor":
        self = cls.__new__(cls)
        self.data_dir = None
        self._fit_from(events_df, grid_df, weights, shape_only, interval_table)
        return self

    def _fit_from(
        self, events_df: pd.DataFrame, grid_df: pd.DataFrame, weights: pd.Series | None = None,
        shape_only: pd.DataFrame | None = None, interval_table: pd.Series | None = None,
    ) -> None:
        self.shape_curve, self.r2_table, self.category_share, self.bar_share = \
            fit_demand_curves(events_df, grid_df, weights, shape_only)
        self.historical_mean_total = float(events_df["total_drinks"].mean())
        self.historical_n = int(len(events_df))
        self._events_df = events_df
        # None unless a caller fit it explicitly via fit_interval_table
        # (expensive — an LOO refit per training event — so it is never
        # computed implicitly here). predict() falls back to a rough
        # (1 - r2) proxy when this is absent; see _interp_half_width.
        self.interval_table = interval_table

    @classmethod
    def from_bundle(cls, bundle: dict) -> "DemandPredictor":
        """Reconstruct a predictor from a retrain.py bundle (the exact
        dict pickled to model_artifacts) WITHOUT refitting — the bundle
        already carries fitted curves, so this just assigns them
        directly. Used by loader.py to serve predictions from the
        active model_artifacts row; from_dataframes/__init__ are for
        fitting from raw data (training/validation/retrain), not serving.

        Raises IncompatibleArtifactFormatError if the bundle's
        format_version doesn't match FORMAT_VERSION — including bundles
        with no format_version at all (anything written before this
        check existed). Refusing to guess is the point: a silently
        wrong/partial predictor is worse than a loud, named failure the
        caller (loader.py) can log and report accurately.
        """
        bundle_version = bundle.get("format_version")
        if bundle_version != FORMAT_VERSION:
            raise IncompatibleArtifactFormatError(
                f"model artifact format_version={bundle_version!r} does not match "
                f"this code's FORMAT_VERSION={FORMAT_VERSION!r} — the artifact was "
                f"written by incompatible code and must be retrained, not loaded."
            )
        self = cls.__new__(cls)
        self.data_dir = None
        self.shape_curve = bundle["shape_curve"]
        self.r2_table = bundle["r2_table"]
        self.category_share = bundle["category_share"]
        self.bar_share = bundle["bar_share"]
        self.interval_table = bundle.get("interval_table")
        self.historical_mean_total = bundle["historical_mean_total"]
        self.historical_n = bundle["historical_n"]
        self._events_df = None
        return self

    def _interp_shape(self, hour_offset: float) -> float:
        return float(np.interp(
            hour_offset, HOUR_GRID, self.shape_curve.to_numpy(),
            left=0.0, right=self.shape_curve.iloc[-1],
        ))

    def shape_fraction_at(self, hour_offset: float) -> float:
        """Public wrapper around the interpolated cumulative-shape
        fraction at a given hour, for use outside a drinks prediction
        (Day 4: projecting live guest-count-so-far to a final estimate
        by reusing this model's shape curve as an approximation for
        guest-arrival timing — there is no dedicated guest-count model;
        both drinks and guest arrivals track cumulative event activity
        reasonably well, but this is an approximation, not a fit)."""
        return self._interp_shape(hour_offset)

    def _interp_r2(self, hour_offset: float) -> float:
        return float(np.interp(
            hour_offset, HOUR_GRID, self.r2_table.to_numpy(),
            left=0.0, right=self.r2_table.iloc[-1],
        ))

    def _interp_category_share(self, category: str, hour: float) -> float:
        return float(np.interp(
            hour, HOUR_GRID, self.category_share[category].to_numpy(),
            left=self.category_share[category].iloc[0], right=self.category_share[category].iloc[-1],
        ))

    def _interp_bar_share(self, rank: int, hour: float) -> float:
        return float(np.interp(
            hour, HOUR_GRID, self.bar_share[rank].to_numpy(),
            left=self.bar_share[rank].iloc[0], right=self.bar_share[rank].iloc[-1],
        ))

    def _interp_half_width(self, hour_offset: float) -> tuple[float, bool]:
        """Returns (half_width_fraction, is_calibrated). Uses the fitted
        LOO interval_table when available (see fit_interval_table); falls
        back to a rough (1 - r2) proxy otherwise, floored at 5% so the
        band is never a zero-width point estimate. The proxy widens for
        the same reason the calibrated table does — both are driven by
        how little cumulative signal exists yet — but is not backed by
        actual held-out error magnitudes, so callers should prefer a
        fitted table (retrain.py always supplies one) and treat
        is_calibrated=False as "approximate."""
        if self.interval_table is not None:
            hw = float(np.interp(
                hour_offset, HOUR_GRID, self.interval_table.to_numpy(),
                left=self.interval_table.iloc[0], right=self.interval_table.iloc[-1],
            ))
            return hw, True
        r2 = self._interp_r2(hour_offset)
        return max(0.05, 1.0 - r2), False

    def predict(
        self, drinks_so_far: float, hour_offset_from_start: float, *, hot_night: bool = False,
    ) -> dict:
        """Predict remaining-hours drinks demand, broken down by
        (bar_rank, category, hour). Mirrors NowcastPredictor.predict()'s
        calibration exactly for the overall total; see module docstring
        for why category/bar shares are historical-only in this version.

        hot_night: applies apply_hot_night_boost() to the category split
        for hours 1-5 — see that function's docstring. Off by default;
        callers must opt in explicitly (events.hot_night_override).

        Returns:
          predicted_final_total: point estimate for the whole event
          confidence: r² at this hour (0 pre-signal, ->1 late in the night)
          confidence_interval: {lower, upper, half_width_pct, calibrated}
              around predicted_final_total — widens exactly where
              confidence is low, since both are driven by the same
              cumulative-signal scarcity; see _interp_half_width
          predicted_by_hour: {hour: {bar_rank: {category: incremental_count}}}
              for every hour-grid point still ahead of hour_offset_from_start
        """
        f_now = self._interp_shape(hour_offset_from_start)
        fallback_used = drinks_so_far <= 0 or f_now < 1e-3
        if fallback_used:
            predicted_final = self.historical_mean_total
            confidence = 0.0
        else:
            predicted_final = drinks_so_far / f_now
            confidence = self._interp_r2(hour_offset_from_start)

        half_width, interval_calibrated = self._interp_half_width(hour_offset_from_start)
        confidence_interval = {
            "lower": round(max(0.0, predicted_final * (1.0 - half_width)), 1),
            "upper": round(predicted_final * (1.0 + half_width), 1),
            "half_width_pct": round(half_width * 100.0, 1),
            "calibrated": interval_calibrated,
        }

        predicted_by_hour: dict = {}
        prev_cum_fraction = self._interp_shape(hour_offset_from_start)
        for hr in HOUR_GRID:
            if hr <= hour_offset_from_start:
                continue
            cum_fraction = self._interp_shape(hr)
            incremental_fraction = max(0.0, cum_fraction - prev_cum_fraction)
            prev_cum_fraction = cum_fraction
            incremental_total = predicted_final * incremental_fraction

            cat_fracs = {cat: self._interp_category_share(cat, hr) for cat in DRINK_CATEGORIES}
            if hot_night:
                cat_fracs = apply_hot_night_boost(cat_fracs, float(hr))

            by_bar: dict = {}
            for rank in BAR_RANKS:
                bar_frac = self._interp_bar_share(rank, hr)
                by_cat = {
                    cat: round(incremental_total * bar_frac * cat_frac, 3)
                    for cat, cat_frac in cat_fracs.items()
                }
                by_bar[rank] = by_cat
            predicted_by_hour[round(float(hr), 1)] = by_bar

        return {
            "predicted_final_total": round(float(predicted_final), 2),
            "confidence": round(float(confidence), 4),
            "confidence_interval": confidence_interval,
            "fallback_used": fallback_used,
            "historical_n": self.historical_n,
            "predicted_by_hour": predicted_by_hour,
            "hot_night_applied": hot_night,
        }
