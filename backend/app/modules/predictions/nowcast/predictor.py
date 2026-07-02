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
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HOUR_GRID = np.arange(0, 11, 1.0)  # elapsed hours since first tx: 0..10
DATA_DIR = Path(__file__).parent / "data"
REQUIRED_FILES = ("training_events.parquet", "training_transactions.parquet")


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


class NowcastPredictor:
    """Stateless-per-call revenue nowcast. Fit once at construction
    (either from parquet, via __init__, or from arbitrary in-memory
    DataFrames, via from_dataframes for back-testing), then call
    predict() as many times as you like — it never mutates state.
    """

    def __init__(self, data_dir: str | Path = DATA_DIR) -> None:
        data_dir = Path(data_dir)
        _assert_data_present(data_dir)
        events_df = pd.read_parquet(data_dir / "training_events.parquet")
        transactions_df = pd.read_parquet(data_dir / "training_transactions.parquet")
        self._fit_from(events_df, transactions_df)

    @classmethod
    def from_dataframes(
        cls, events_df: pd.DataFrame, transactions_df: pd.DataFrame,
    ) -> "NowcastPredictor":
        """Build a predictor from in-memory DataFrames instead of
        parquet files — used by the leave-one-out back-test so each
        fold can fit on an 8-event subset."""
        self = cls.__new__(cls)
        self._fit_from(events_df, transactions_df)
        return self

    def _fit_from(self, events_df: pd.DataFrame, transactions_df: pd.DataFrame) -> None:
        self.shape_curve, self.r2_table = fit_shape_and_r2(events_df, transactions_df)
        self.historical_mean = float(events_df["total_revenue"].mean())
        self.historical_range_eur = (
            float(events_df["total_revenue"].min()),
            float(events_df["total_revenue"].max()),
        )
        self.historical_n = int(len(events_df))

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

    def predict(self, current_revenue_eur: float, hour_offset_from_start: float) -> dict:
        """Predict final event revenue given how much has landed so far
        and how many hours since the event's first transaction.

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
          historical_range_eur: (min, max) of the historical events
              this predictor was fit on
          historical_n: how many historical events this was fit on
        """
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
        if current_revenue_eur <= 0 or f_now < 1e-3:
            predicted_final = self.historical_mean
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
        }


# ─── Process-wide singleton ─────────────────────────────────────────
# Loaded once, the first time this module is imported (i.e. at app
# startup, since events/router.py imports get_predictor() at module
# load time) — NOT on every request. Fails loudly at import time if
# the parquet data is missing, rather than on the first request.
_predictor: NowcastPredictor | None = None


def get_predictor() -> NowcastPredictor:
    global _predictor
    if _predictor is None:
        _predictor = NowcastPredictor()
    return _predictor


# Eager singleton init at import time (see module docstring above).
_predictor = NowcastPredictor()
