"""One-off CLI: report the LOO-calibrated confidence band at hours 2, 4,
6, 8 for a venue-total prediction, using the exact production training
set (11 events + Jul-5 shape-only, uniform weighting) — Day 3 closeout
item B. Not wired into retrain.py's runtime path; retrain.py fits and
persists its own interval_table per run. This script exists to surface
the numbers for review, mirroring demand_loo_experiment.py's role.
"""
from __future__ import annotations

from app.modules.predictions.demand.predictor import DemandPredictor, fit_interval_table
from app.scripts.demand_loo_experiment import _load_all


def main() -> None:
    full, jul5_shape_only = _load_all()
    interval_table = fit_interval_table(full.events, full.grid, None, jul5_shape_only)
    predictor = DemandPredictor.from_dataframes(full.events, full.grid, None, jul5_shape_only, interval_table)

    mean_total = full.events["total_drinks"].mean()
    print(f"Reference: mean training-event total = {mean_total:.0f} drinks\n")
    print(f"{'hour':>4s}  {'r2 (confidence)':>16s}  {'half_width':>10s}  {'example band @ mean total':>28s}")
    for h in (2.0, 4.0, 6.0, 8.0):
        # Illustrative: "we're h hours in, having observed a plausible
        # share of the mean total" -- drives predicted_final_total close
        # to mean_total so the band's width is easy to read in isolation
        # from calibration drift.
        f_h = predictor._interp_shape(h)
        observed = mean_total * f_h
        result = predictor.predict(drinks_so_far=float(observed), hour_offset_from_start=h)
        ci = result["confidence_interval"]
        print(f"{h:4.0f}  {result['confidence']:16.3f}  {ci['half_width_pct']:9.1f}%  "
              f"[{ci['lower']:.0f}, {result['predicted_final_total']:.0f}, {ci['upper']:.0f}]")


if __name__ == "__main__":
    main()
