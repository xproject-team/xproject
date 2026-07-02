"""predictor.py — the "ML Predicted" revenue nowcast.

Product name shown to the user: "ML Predicted" — a design decision,
like a moving-average line in TradingView: the label describes the
PRODUCT, not the algorithm underneath. Internally this is a plain
statistical nowcast (historical shape curve + linear scaling), not a
trained model. Post-Sundance the guts get upgraded to something
trained on more seasons of data; the label doesn't change.

Pure pandas + numpy. No sklearn, no .pkl artifacts.

Moved here from backend/scripts/nowcast_predictor.py (Phase C) as part
of Phase D — same class API, now backed by parquet files shipped
alongside this module (nowcast/data/*.parquet) instead of a scratch
scripts/ml_data/ directory, and loaded once as a process-wide
singleton (see get_predictor() below) instead of per-script-run.

─── Method (unchanged from Phase C, matches Phase B's Q1/Q4) ──────────
1. For each historical event, interpolate its cumulative-revenue curve
   onto a common hour grid (0..10h since first transaction), holding
   the value constant at the event's final total past its last
   transaction (the event is simply over by then, not "missing data").
2. Normalize each event's curve by ITS OWN final revenue -> a "fraction
   of final revenue reached by hour h" curve per event.
3. shape_curve = the mean of those normalized curves, per hour.
4. r2_table = Pearson r² between (cumulative revenue at hour h across
   events) and (final revenue across events), per hour — the
   confidence table.

Outliers are NOT dropped from the fit (see Phase C report — a
low-revenue night still follows roughly the same accumulation SHAPE;
dropping it would understate real variance).

─── Phase F — what shipped and what didn't ────────────────────────────
Phase F set out to add year-segmented shape curves, hour-of-day
weighting, a first-hour signal booster, and per-year confidence
recalibration. All four were built and leave-one-out back-tested
against the Phase C baseline (see backend/scripts/test_nowcast_predictor.py).
Every one of them made MAPE WORSE at every hour checkpoint (h2/4/6/8),
and monotonically worse the harder the year-weighting was applied —
even a 25%-shrunk blend toward the year-specific curve was worse than
0% (i.e. the original unsegmented curve). Root cause: splitting 9
events across 2 years leaves 4 and 5 events per curve, and per-year r²
was outright unstable noise at that n (e.g. 2024's r² at hour 7 came
out to 0.011 — worse than a coin flip — purely from sample-size
variance, not signal). Per this module's own stated principle ("Do not
ship a 'more sophisticated' model that performs worse than the simple
one"), all four were reverted. shape_curve and r2_table below are
UNCHANGED from Phase C/D — still fit on the full unsegmented 9-event
(now growing via auto-retrain) sample.

The one Phase F change that DID ship: a year-weighted fallback mean
(see year_weighted_fallback_mean below), used only in the pre-event /
no-revenue-yet fallback path. It doesn't touch the tested h2-h8
metrics at all (that path never fires once there's real revenue to
scale from), and using a recency-weighted prior instead of a flat
all-time mean for a "we have zero signal yet" estimate is a safe,
independently-justified improvement — not the same class of claim as
the reverted shape-curve changes.

Also shipped: auto-retraining (retrain.py) so shape_curve/r2_table
keep growing with real data after every completed event. Once there
are enough events for a reasonable per-year split (rough rule of
thumb: 8-10+ per year), year-segmentation may be worth re-testing —
the back-test script is right there.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HOUR_GRID = np.arange(0, 11, 1.0)  # elapsed hours since first tx: 0..10
DATA_DIR = Path(__file__).parent / "data"
REQUIRED_FILES = ("training_events.parquet", "training_transactions.parquet")
MTIME_CHECK_INTERVAL_S = 60.0  # how often get_predictor() re-stats the parquet files


def _assert_data_present(data_dir: Path) -> None:
    """Fail loudly (not with a confusing pandas FileNotFoundError deep
    in a stack trace) if the parquet files this module needs aren't
    shipped alongside it."""
    missing = [f for f in REQUIRED_FILES if not (data_dir / f).exists()]
    if missing:
        raise FileNotFoundError(
            f"NowcastPredictor cannot start: missing {missing} in {data_dir}. "
            f"Regenerate via backend/scripts/extract_historical_sundance.py "
            f"and copy training_events.parquet + training_transactions.parquet "
            f"into {data_dir}."
        )


def fit_shape_and_r2(
    events_df: pd.DataFrame, transactions_df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    """Fit shape_curve and r2_table from a set of historical events.

    A free function (not a method) so back-testing can call it directly
    on a leave-one-out subset without needing a full NowcastPredictor
    instance per fold — see backend/scripts/test_nowcast_predictor.py.
    """
    tx = transactions_df.merge(
        events_df[["event_id", "first_tx_time"]], on="event_id", how="inner",
    )
    tx["elapsed_hr"] = (tx["timestamp"] - tx["first_tx_time"]).dt.total_seconds() / 3600.0
    tx = tx.sort_values(["event_id", "timestamp"])
    tx["cum_revenue"] = tx.groupby("event_id")["amount_eur"].cumsum()

    totals = events_df.set_index("event_id")["total_revenue"]

    matrix: dict[str, np.ndarray] = {}
    for eid, g in tx.groupby("event_id"):
        x = g["elapsed_hr"].to_numpy()
        y = g["cum_revenue"].to_numpy()
        matrix[eid] = np.interp(HOUR_GRID, x, y, left=0.0, right=totals[eid])
    matrix_df = pd.DataFrame(matrix, index=HOUR_GRID).T  # events x hours

    finals = totals.reindex(matrix_df.index)
    normalized = matrix_df.div(finals, axis=0)
    shape_curve = normalized.mean(axis=0)  # Series indexed by HOUR_GRID

    r2_values = {}
    for hr in HOUR_GRID:
        col = matrix_df[hr]
        if col.std() == 0 or finals.std() == 0:
            r2_values[hr] = 0.0
        else:
            r = np.corrcoef(col, finals)[0, 1]
            r2_values[hr] = float(r ** 2)
    r2_table = pd.Series(r2_values)

    return shape_curve, r2_table


def year_weighted_fallback_mean(events_df: pd.DataFrame, target_year: int) -> float:
    """Recency-weighted historical mean for the pre-event / no-revenue
    fallback: the most recent 2 years at-or-before target_year, newest
    weighted 2x. E.g. for target_year=2026 with 2024+2025 in the
    training data: (2 * 2025_mean + 1 * 2024_mean) / 3.

    Falls back to the plain all-time mean if fewer than 1 year is
    at-or-before target_year (shouldn't happen once there's any
    training data, but keeps this total rather than partial).

    This is the one Phase F "year feature" that survived back-testing
    — see the module docstring's Phase F section for why the others
    (year-segmented shape_curve, r2_table) did NOT ship.
    """
    years = pd.to_datetime(events_df["event_date"]).dt.year
    years_present = sorted(years.unique())
    candidates = sorted([y for y in years_present if y <= target_year], reverse=True)[:2]
    if not candidates:
        candidates = years_present[:1]
    if not candidates:
        return float(events_df["total_revenue"].mean())

    weights = {yr: (2.0 if i == 0 else 1.0) for i, yr in enumerate(candidates)}
    total_w = sum(weights.values())
    weighted_sum = sum(
        w * float(events_df[years == yr]["total_revenue"].mean())
        for yr, w in weights.items()
    )
    return weighted_sum / total_w


class NowcastPredictor:
    """Stateless-per-call revenue nowcast. Fit once at construction
    (either from parquet, via __init__, or from arbitrary in-memory
    DataFrames, via from_dataframes for back-testing), then call
    predict() as many times as you like — it never mutates state.
    """

    def __init__(self, data_dir: str | Path = DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        events_df, transactions_df = self._load_parquet(self.data_dir)
        self._fit_from(events_df, transactions_df)
        self.training_last_updated_at = self._data_mtime(self.data_dir)

    @staticmethod
    def _load_parquet(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
        _assert_data_present(data_dir)
        events_df = pd.read_parquet(data_dir / "training_events.parquet")
        transactions_df = pd.read_parquet(data_dir / "training_transactions.parquet")
        return events_df, transactions_df

    @staticmethod
    def _data_mtime(data_dir: Path) -> datetime:
        latest = max((data_dir / f).stat().st_mtime for f in REQUIRED_FILES)
        return datetime.fromtimestamp(latest, tz=timezone.utc)

    @classmethod
    def from_dataframes(
        cls, events_df: pd.DataFrame, transactions_df: pd.DataFrame,
    ) -> "NowcastPredictor":
        """Build a predictor from in-memory DataFrames instead of
        parquet files — used by the leave-one-out back-test so each
        fold can fit on an 8-event subset. No data_dir, so reload()
        isn't available and training_last_updated_at is "now"."""
        self = cls.__new__(cls)
        self.data_dir = None
        self._fit_from(events_df, transactions_df)
        self.training_last_updated_at = datetime.now(timezone.utc)
        return self

    def reload(self) -> None:
        """Re-read the parquet files and re-fit in place. Called by
        get_predictor() when it notices the files changed on disk
        (see MTIME_CHECK_INTERVAL_S below) — i.e. after retrain.py has
        atomically written a fresh training set post-event-completion."""
        if self.data_dir is None:
            raise RuntimeError("reload() requires a predictor built from parquet (data_dir set)")
        events_df, transactions_df = self._load_parquet(self.data_dir)
        self._fit_from(events_df, transactions_df)
        self.training_last_updated_at = self._data_mtime(self.data_dir)

    def _fit_from(self, events_df: pd.DataFrame, transactions_df: pd.DataFrame) -> None:
        self.shape_curve, self.r2_table = fit_shape_and_r2(events_df, transactions_df)
        self.historical_mean = float(events_df["total_revenue"].mean())
        self.historical_range_eur = (
            float(events_df["total_revenue"].min()),
            float(events_df["total_revenue"].max()),
        )
        self.historical_n = int(len(events_df))
        self._events_df = events_df  # kept for year_weighted_fallback_mean at predict() time

    # ─── Interpolation helpers ──────────────────────────────────────

    def _interp_shape(self, hour_offset: float) -> float:
        return float(np.interp(
            hour_offset, HOUR_GRID, self.shape_curve.to_numpy(),
            left=0.0, right=self.shape_curve.iloc[-1],
        ))

    def _interp_r2(self, hour_offset: float) -> float:
        return float(np.interp(
            hour_offset, HOUR_GRID, self.r2_table.to_numpy(),
            left=0.0, right=self.r2_table.iloc[-1],
        ))

    # ─── Public API ──────────────────────────────────────────────────

    def predict(
        self,
        current_revenue_eur: float,
        hour_offset_from_start: float,
        target_year: int | None = None,
    ) -> dict:
        """Predict final event revenue given how much has landed so far
        and how many hours since the event's first transaction.

        target_year: the calendar year of the event being predicted
            (e.g. event.scheduled_at.year). Only affects the pre-event
            fallback mean (see year_weighted_fallback_mean) — shape_curve
            and r2_table are NOT year-segmented; see the module
            docstring's "Phase F — what shipped and what didn't"
            section for why. Defaults to the current year.

        Returns:
          predicted_final_revenue_eur: point estimate
          predicted_curve: {hour_offset: predicted cumulative revenue}
              for every hour-grid point still ahead of hour_offset_from_start
          confidence: r² of "cumulative revenue at this hour predicts
              final revenue," from the historical fit — 0.0 if we're
              pre-event / in the first minutes (nothing to scale from
              yet); 1.0 once hour_offset_from_start >= 10 (the event's
              effectively over, extrapolated flat from r2_table's last
              point which is exactly 1.0).
          vs_historical_avg_eur: predicted_final - historical mean
              (the plain all-time mean, same in both branches — kept
              as a stable, unambiguous reference point rather than a
              moving year-weighted target).
          historical_range_eur: (min, max) of the historical events
              this predictor was fit on
          historical_n: how many historical events this was fit on
          year_weighted_prior_used: True only when the pre-event
              fallback fired (the only branch where the year-weighted
              mean is actually used as the estimate).
        """
        if target_year is None:
            target_year = datetime.now(timezone.utc).year

        f_now = self._interp_shape(hour_offset_from_start)

        # Pre-event / first-minutes fallback. Two conditions, either one
        # triggers it:
        #   - no revenue has landed yet (the literal "pre-event" case)
        #   - f_now is negligible (< 0.1% of a typical night's revenue
        #     is normally in by now). shape_curve[0] is NOT exactly 0.0
        #     in practice (one historical event had a trace of revenue
        #     at minute zero, per Phase C's fit) — dividing by a
        #     near-zero fraction would extrapolate a tiny bit of early
        #     revenue into an absurd final estimate, which is worse
        #     than just admitting "not enough signal yet."
        year_weighted_prior_used = current_revenue_eur <= 0 or f_now < 1e-3
        if year_weighted_prior_used:
            predicted_final = year_weighted_fallback_mean(self._events_df, target_year)
            confidence = 0.0
        else:
            predicted_final = current_revenue_eur / f_now
            confidence = self._interp_r2(hour_offset_from_start)

        predicted_curve = {
            round(float(hr), 1): round(predicted_final * self._interp_shape(hr), 2)
            for hr in HOUR_GRID
            if hr > hour_offset_from_start
        }

        return {
            "predicted_final_revenue_eur": round(float(predicted_final), 2),
            "predicted_curve": predicted_curve,
            "confidence": round(float(confidence), 4),
            "vs_historical_avg_eur": round(float(predicted_final - self.historical_mean), 2),
            "historical_range_eur": self.historical_range_eur,
            "historical_n": self.historical_n,
            "training_events_count": self.historical_n,
            "training_last_updated_at": self.training_last_updated_at,
            "year_weighted_prior_used": year_weighted_prior_used,
        }


# ─── Process-wide singleton ─────────────────────────────────────────
# Loaded once, the first time this module is imported (i.e. at app
# startup, since events/router.py imports get_predictor() at module
# load time) — NOT on every request. Fails loudly at import time if
# the parquet data is missing, rather than on the first request.
#
# Phase F auto-retrain (retrain.py) runs in a separate arq worker
# process and atomically rewrites the parquet files after each
# completed event. That worker process's own predictor instance
# reloading itself wouldn't help the web process — they're different
# Python processes with independent memory. So get_predictor() here
# polls the parquet files' mtime (throttled to once every
# MTIME_CHECK_INTERVAL_S, not on every request) and calls reload() when
# it notices they changed. Both the web process and the worker process
# independently detect the change this way — no cross-process signaling
# needed.
_predictor: NowcastPredictor | None = None
_last_mtime_check: float = 0.0


def get_predictor() -> NowcastPredictor:
    global _predictor, _last_mtime_check

    if _predictor is None:
        _predictor = NowcastPredictor()
        _last_mtime_check = time.monotonic()
        return _predictor

    now = time.monotonic()
    if now - _last_mtime_check >= MTIME_CHECK_INTERVAL_S:
        _last_mtime_check = now
        if _predictor.data_dir is not None:
            try:
                latest_mtime = NowcastPredictor._data_mtime(_predictor.data_dir)
                if latest_mtime > _predictor.training_last_updated_at:
                    _predictor.reload()
            except OSError:
                # Data dir transiently unavailable mid-atomic-rename —
                # keep serving the current model, try again next check.
                pass

    return _predictor


# Eager singleton init at import time (see module docstring above).
_predictor = NowcastPredictor()
_last_mtime_check = time.monotonic()
