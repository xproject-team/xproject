#!/usr/bin/env python3
"""explore_ml_data.py — Phase B: exploration + feature engineering audit
for the Sundance revenue-prediction ML feature.

THROWAWAY / OFFLINE ANALYSIS SCRIPT. Read-only against Phase A's parquet
output (backend/scripts/ml_data/*.parquet) plus two specific CSVs under
data/sundance-{year}/ (orders_summary.csv for deposit_eur,
data/sundance-2024/attendance.csv for attendance). Does NOT merge or
reconcile the two extractions — this is pure exploration to inform
which features are worth building in Phase C.

Usage (from backend/):
    venv/bin/python scripts/explore_ml_data.py

Prints markdown-flavored findings to stdout, one section per question
(Q1-Q6), and saves every plot to backend/scripts/ml_data/plots/.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless — no display server in this environment
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).parent
ML_DATA_DIR = SCRIPT_DIR / "ml_data"
PLOTS_DIR = ML_DATA_DIR / "plots"
REPO_ROOT = SCRIPT_DIR.parents[1]  # backend/scripts -> backend -> xproject
DATA_DIR = REPO_ROOT / "data"

HOUR_GRID = np.arange(0, 11, 1.0)  # elapsed hours since first tx: 0..10


def h(title: str, level: int = 2) -> None:
    print("\n" + ("#" * level) + " " + title + "\n")


def load_phase_a() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    tx = pd.read_parquet(ML_DATA_DIR / "training_transactions.parquet")
    ev = pd.read_parquet(ML_DATA_DIR / "training_events.parquet")
    bars = pd.read_parquet(ML_DATA_DIR / "training_bars.parquet")
    return tx, ev, bars


def build_elapsed_hours(tx: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """Attach elapsed_hr (hours since THIS event's first transaction) and
    cum_revenue (running total within the event, sorted by time)."""
    merged = tx.merge(ev[["event_id", "first_tx_time"]], on="event_id", how="left")
    merged["elapsed_hr"] = (
        merged["timestamp"] - merged["first_tx_time"]
    ).dt.total_seconds() / 3600.0
    merged = merged.sort_values(["event_id", "timestamp"])
    merged["cum_revenue"] = merged.groupby("event_id")["amount_eur"].cumsum()
    return merged


def hourly_cumulative_matrix(tx_elapsed: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """events x HOUR_GRID matrix of cumulative revenue, interpolated per
    event. Past an event's last transaction, the value is held constant
    at that event's final total (querying 'cumulative revenue at hour 10'
    for an event that ended at hour 9.3 correctly returns its final
    total, not NaN — the event is just over by then)."""
    totals = ev.set_index("event_id")["total_revenue"]
    rows = {}
    for eid, g in tx_elapsed.groupby("event_id"):
        x = g["elapsed_hr"].to_numpy()
        y = g["cum_revenue"].to_numpy()
        rows[eid] = np.interp(HOUR_GRID, x, y, left=0.0, right=totals[eid])
    return pd.DataFrame(rows, index=HOUR_GRID).T  # events x hours


# ─── Q1 ──────────────────────────────────────────────────────────────

def q1_cumulative_curves(tx_elapsed: pd.DataFrame, ev: pd.DataFrame, matrix: pd.DataFrame) -> None:
    h("Q1 — Per-event cumulative revenue curve")

    event_ids = sorted(tx_elapsed["event_id"].unique())

    # Overlay
    fig, ax = plt.subplots(figsize=(10, 6))
    for eid in event_ids:
        g = tx_elapsed[tx_elapsed["event_id"] == eid]
        ax.plot(g["elapsed_hr"], g["cum_revenue"], label=eid, linewidth=1.5)
    ax.set_xlabel("Hours since first transaction")
    ax.set_ylabel("Cumulative revenue (EUR)")
    ax.set_title("Cumulative revenue — all 9 events overlaid")
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "q1_overlay.png", dpi=120)
    plt.close(fig)

    # Small multiples
    fig, axes = plt.subplots(3, 3, figsize=(14, 10), sharex=True)
    for ax, eid in zip(axes.flat, event_ids):
        g = tx_elapsed[tx_elapsed["event_id"] == eid]
        ax.plot(g["elapsed_hr"], g["cum_revenue"], color="tab:blue")
        ax.set_title(eid.replace("sundance_", ""), fontsize=9)
        ax.grid(alpha=0.3)
    fig.suptitle("Cumulative revenue — small multiples")
    fig.supxlabel("Hours since first transaction")
    fig.supylabel("Cumulative revenue (EUR)")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "q1_small_multiples.png", dpi=120)
    plt.close(fig)

    # Shape-consistency: normalize each event's curve by its own final
    # revenue, then look at the spread (std) across events at each hour.
    normalized = matrix.div(ev.set_index("event_id")["total_revenue"], axis=0)
    fig, ax = plt.subplots(figsize=(9, 5))
    for eid in event_ids:
        ax.plot(HOUR_GRID, normalized.loc[eid], alpha=0.6, linewidth=1.2)
    ax.plot(HOUR_GRID, normalized.mean(axis=0), color="black", linewidth=2.5, label="mean")
    ax.fill_between(
        HOUR_GRID,
        normalized.mean(axis=0) - normalized.std(axis=0),
        normalized.mean(axis=0) + normalized.std(axis=0),
        color="black", alpha=0.15, label="±1 std",
    )
    ax.set_xlabel("Hours since first transaction")
    ax.set_ylabel("Fraction of final revenue reached")
    ax.set_title("Normalized cumulative shape — consistency across events")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "q1_normalized_shape.png", dpi=120)
    plt.close(fig)

    print(f"Saved: q1_overlay.png, q1_small_multiples.png, q1_normalized_shape.png")
    print()
    print("Normalized shape (fraction of final revenue reached), mean ± std by elapsed hour:")
    print()
    print("| hour | mean_frac | std_frac |")
    print("|---|---|---|")
    for hr in HOUR_GRID:
        print(f"| {hr:.0f} | {normalized.mean(axis=0)[hr]:.3f} | {normalized.std(axis=0)[hr]:.3f} |")

    max_std_hr = normalized.std(axis=0).idxmax()
    print()
    print(f"**Finding:** shape is most variable at hour {max_std_hr:.0f} "
          f"(std={normalized.std(axis=0)[max_std_hr]:.3f}) — events diverge most there. "
          f"Std shrinks toward 0 near the end (curves must converge to 1.0 by definition).")


# ─── Q2 ──────────────────────────────────────────────────────────────

def q2_hourly_distribution(tx: pd.DataFrame) -> None:
    h("Q2 — Hourly revenue distribution (clock time, all events combined)")

    tx = tx.copy()
    tx["hour_of_day"] = tx["timestamp"].dt.hour
    by_hour = tx.groupby("hour_of_day").agg(
        tx_count=("amount_eur", "count"),
        revenue=("amount_eur", "sum"),
    ).reindex(range(12, 24), fill_value=0)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 8), sharex=True)
    ax1.bar(by_hour.index, by_hour["tx_count"], color="tab:blue")
    ax1.set_ylabel("Transaction count")
    ax1.set_title("Transactions per hour-of-day (all 9 events combined)")
    ax1.grid(alpha=0.3)

    ax2.bar(by_hour.index, by_hour["revenue"], color="tab:green")
    ax2.set_ylabel("Revenue (EUR)")
    ax2.set_xlabel("Hour of day (24h clock)")
    ax2.set_title("Revenue per hour-of-day (all 9 events combined)")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "q2_hourly_distribution.png", dpi=120)
    plt.close(fig)

    print("Saved: q2_hourly_distribution.png")
    print()
    print("| hour | tx_count | revenue_eur | pct_of_total_revenue |")
    print("|---|---|---|---|")
    total_rev = by_hour["revenue"].sum()
    for hr, row in by_hour.iterrows():
        pct = (row["revenue"] / total_rev * 100) if total_rev else 0
        print(f"| {hr:02d}:00 | {int(row['tx_count'])} | {row['revenue']:,.0f} | {pct:.1f}% |")

    peak_hour = by_hour["revenue"].idxmax()
    print()
    print(f"**Finding:** peak revenue hour is {peak_hour:02d}:00-{peak_hour+1:02d}:00 "
          f"(€{by_hour.loc[peak_hour, 'revenue']:,.0f}, "
          f"{by_hour.loc[peak_hour, 'revenue']/total_rev*100:.1f}% of all revenue).")


# ─── Q3 ──────────────────────────────────────────────────────────────

def q3_summary_table(tx: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    h("Q3 — Per-event summary stats")

    tx = tx.copy()
    tx["hour_of_day"] = tx["timestamp"].dt.hour
    peak_by_event = (
        tx.groupby(["event_id", "hour_of_day"])["amount_eur"].sum()
        .groupby("event_id").max()
    )

    rows = []
    for _, e in ev.iterrows():
        duration_hrs = (e["last_tx_time"] - e["first_tx_time"]).total_seconds() / 3600.0
        rows.append({
            "event_date": e["event_date"],
            "total_revenue": e["total_revenue"],
            "tx_count": e["transaction_count"],
            "unique_bars": e["bar_count"],
            "first_tx": e["first_tx_time"],
            "last_tx": e["last_tx_time"],
            "event_duration_hrs": round(duration_hrs, 2),
            "revenue_per_hour": round(e["total_revenue"] / duration_hrs, 1) if duration_hrs else None,
            "peak_hour_revenue": peak_by_event.get(e["event_id"], None),
        })
    summary = pd.DataFrame(rows)

    print("| event_date | total_revenue | tx_count | unique_bars | first_tx | last_tx | "
          "duration_hrs | revenue/hr | peak_hour_revenue |")
    print("|---|---|---|---|---|---|---|---|---|")
    for _, r in summary.iterrows():
        print(f"| {r['event_date']} | €{r['total_revenue']:,.0f} | {r['tx_count']} | "
              f"{r['unique_bars']} | {r['first_tx'].strftime('%H:%M')} | "
              f"{r['last_tx'].strftime('%H:%M')} | {r['event_duration_hrs']} | "
              f"€{r['revenue_per_hour']:,.0f} | €{r['peak_hour_revenue']:,.0f} |")

    print()
    print(f"**Across all 9 events:** revenue range €{summary['total_revenue'].min():,.0f}–"
          f"€{summary['total_revenue'].max():,.0f}, mean €{summary['total_revenue'].mean():,.0f}, "
          f"duration range {summary['event_duration_hrs'].min():.1f}–{summary['event_duration_hrs'].max():.1f}h.")
    return summary


# ─── Q4 ──────────────────────────────────────────────────────────────

def q4_predictive_correlation(matrix: pd.DataFrame, ev: pd.DataFrame) -> float | None:
    h("Q4 — Cross-event correlation: does revenue at hour H predict the final number?")

    finals = ev.set_index("event_id")["total_revenue"].reindex(matrix.index)

    r2_by_hour = {}
    for hr in HOUR_GRID:
        partial = matrix[hr]
        if partial.std() == 0 or finals.std() == 0:
            r2_by_hour[hr] = float("nan")
            continue
        r = np.corrcoef(partial, finals)[0, 1]
        r2_by_hour[hr] = r ** 2

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(HOUR_GRID, [r2_by_hour[hr] for hr in HOUR_GRID], marker="o", color="tab:red")
    ax.axhline(0.90, color="gray", linestyle="--", label="r² = 0.90 threshold")
    ax.set_xlabel("Hours since first transaction")
    ax.set_ylabel("r² (cumulative revenue at hour H vs. final revenue)")
    ax.set_title("Predictive power of partial-night revenue (n=9 events)")
    ax.set_ylim(0, 1.05)
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "q4_r2_by_hour.png", dpi=120)
    plt.close(fig)

    print("Saved: q4_r2_by_hour.png")
    print()
    print("**Caveat: n=9 events — r² at this sample size is noisy; treat as directional, "
          "not a statistically robust threshold.**")
    print()
    print("| elapsed_hour | r² (cum revenue @ hour vs final) |")
    print("|---|---|")
    threshold_hour = None
    for hr in HOUR_GRID:
        val = r2_by_hour[hr]
        flag = " <-- first ≥0.90" if (not np.isnan(val) and val >= 0.90 and threshold_hour is None) else ""
        print(f"| {hr:.0f} | {val:.3f}{flag} |")
        if not np.isnan(val) and val >= 0.90 and threshold_hour is None:
            threshold_hour = hr

    print()
    if threshold_hour is not None:
        print(f"**Answer: hour {threshold_hour:.0f}** is the first elapsed-hour offset where "
              f"cumulative revenue reaches r² ≥ 0.90 against final revenue, across the 9 events.")
    else:
        print("**Answer: no elapsed-hour offset in the observed window reaches r² ≥ 0.90** "
              "against final revenue.")
    return threshold_hour


# ─── Q5 ──────────────────────────────────────────────────────────────

def _event_date_str(ev: pd.DataFrame) -> pd.Series:
    """ev['event_date'] holds python date objects (Phase A parquet);
    the CSVs use ISO date strings. Normalize to string for joining."""
    return ev["event_date"].astype(str)


def _load_deposit_eur(ev: pd.DataFrame) -> pd.Series:
    """Sum deposit_eur per event_date from data/sundance-{year}/orders_summary.csv.
    Read-only pull, no merge into Phase A outputs."""
    out: dict[str, float] = {}
    for path in [
        DATA_DIR / "sundance-2024" / "orders_summary.csv",
        DATA_DIR / "sundance-2025" / "orders_summary.csv",
    ]:
        if not path.exists():
            continue
        df = pd.read_csv(path, usecols=["event_date", "deposit_eur"])
        out.update(df.groupby("event_date")["deposit_eur"].sum().to_dict())
    return _event_date_str(ev).map(out)


def _load_attendance(ev: pd.DataFrame) -> pd.Series:
    path = DATA_DIR / "sundance-2024" / "attendance.csv"
    if not path.exists():
        return pd.Series(index=ev.index, dtype=float)
    df = pd.read_csv(path, usecols=["event_date", "total_people"])
    mapping = df.set_index("event_date")["total_people"].to_dict()
    return _event_date_str(ev).map(mapping)


def q5_feature_audit(tx_elapsed: pd.DataFrame, ev: pd.DataFrame) -> None:
    h("Q5 — Feature candidate audit")

    ev = ev.copy()
    ev["event_date_dt"] = pd.to_datetime(ev["event_date"])
    ev["day_of_week"] = ev["event_date_dt"].dt.day_name()
    ev["month"] = ev["event_date_dt"].dt.month
    ev["year"] = ev["event_date_dt"].dt.year

    ev["deposit_eur"] = _load_deposit_eur(ev).values
    ev["attendance"] = _load_attendance(ev).values

    first_hr = tx_elapsed[tx_elapsed["elapsed_hr"] < 1.0].groupby("event_id")["amount_eur"].sum()
    first_2hr = tx_elapsed[tx_elapsed["elapsed_hr"] < 2.0].groupby("event_id")["amount_eur"].sum()
    ev["first_hour_revenue"] = ev["event_id"].map(first_hr).fillna(0)
    ev["first_2h_revenue"] = ev["event_id"].map(first_2hr).fillna(0)

    def corr_with_revenue(col: str) -> tuple[float | None, float | None, int]:
        sub = ev[[col, "total_revenue"]].dropna()
        n = len(sub)
        if n < 3 or sub[col].nunique() < 2:
            return None, None, n
        r = np.corrcoef(sub[col].astype(float), sub["total_revenue"])[0, 1]
        return r, r ** 2, n

    candidates = [
        ("day_of_week", "categorical", False,
         "All 9 events are Sundays (event name literally says so) — zero variance, cannot correlate."),
        ("month", "numeric (6/7/8)", True, "Known the day the event is scheduled — months ahead."),
        ("year", "numeric (2024/2025)", True, "Known trivially in advance."),
        ("deposit_eur", "numeric (EUR)", "partial",
         "Final total only known after the event ends, but accumulates live like revenue — "
         "usable as a running feature DURING an event, not as a pre-event predictor."),
        ("attendance", "numeric (people)", "partial",
         "Ticket pre-sales are known in advance; final total_people (incl. door/free entries) "
         "isn't final until doors close. Coverage: only 4 of 9 events (2024 minus the corrupted Aug-4 row)."),
        ("first_hour_revenue", "numeric (EUR)", True, "Computable live, 1h into the event."),
        ("first_2h_revenue", "numeric (EUR)", True, "Computable live, 2h into the event."),
    ]

    print("| feature | coverage | r | r² | live-computable? | note |")
    print("|---|---|---|---|---|---|")
    for col, dtype, live, note in candidates:
        if col == "day_of_week":
            print(f"| {col} | 9/9 | n/a | n/a | yes (before event) | {note} |")
            continue
        r, r2, n = corr_with_revenue(col)
        r_str = f"{r:.3f}" if r is not None else "n/a"
        r2_str = f"{r2:.3f}" if r2 is not None else "n/a"
        live_str = {"partial": "partial (see note)"}.get(live, "yes" if live else "no")
        print(f"| {col} | {n}/9 | {r_str} | {r2_str} | {live_str} | {note} |")

    print()
    numeric_ranked = []
    for col, *_ in candidates:
        if col == "day_of_week":
            continue
        r, r2, n = corr_with_revenue(col)
        if r2 is not None:
            numeric_ranked.append((col, r2, n))
    numeric_ranked.sort(key=lambda t: t[1], reverse=True)
    print("**Ranked by |r²| (descending):**")
    for col, r2, n in numeric_ranked:
        print(f"  - {col}: r²={r2:.3f} (n={n})")


# ─── Q6 ──────────────────────────────────────────────────────────────

def q6_quality_flags(tx: pd.DataFrame, ev: pd.DataFrame, summary: pd.DataFrame) -> None:
    h("Q6 — Data quality flags")

    flags = []

    for col in ["total_revenue", "tx_count", "revenue_per_hour"]:
        mu, sigma = summary[col].mean(), summary[col].std()
        if sigma == 0:
            continue
        z = (summary[col] - mu) / sigma
        for i, zv in z.items():
            if abs(zv) >= 1.5:
                flags.append(
                    f"{summary.loc[i, 'event_date']}: {col}={summary.loc[i, col]:,.1f} "
                    f"is {zv:+.2f}σ from the group mean ({mu:,.1f})"
                )

    # Hour-of-day gaps: for each event, find clock hours strictly between
    # its first and last tx with zero transactions (a mid-event silent
    # gap — possible POS outage or data loss, not just "event hasn't
    # started/already ended").
    tx = tx.copy()
    tx["hour_of_day"] = tx["timestamp"].dt.hour
    for _, e in ev.iterrows():
        g = tx[tx["event_id"] == e["event_id"]]
        if g.empty:
            continue
        start_h, end_h = g["hour_of_day"].min(), g["hour_of_day"].max()
        active_hours = set(g["hour_of_day"].unique())
        expected_hours = set(range(int(start_h), int(end_h) + 1))
        missing = sorted(expected_hours - active_hours)
        if missing:
            flags.append(f"{e['event_date']}: zero transactions during hour(s) {missing} "
                          f"(active window was {start_h:02d}:00-{end_h:02d}:00) — possible gap")

    if flags:
        print("Flagged:")
        for f in flags:
            print(f"  - {f}")
    else:
        print("No outlier events or hour-of-day gaps detected (all within ~1.5σ, no silent gaps).")


# ─── Main ──────────────────────────────────────────────────────────────

def main() -> int:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    print("# Phase B — ML Data Exploration\n")
    print("Source: backend/scripts/ml_data/*.parquet (Phase A output), "
          "plus read-only pulls from data/sundance-{year}/orders_summary.csv "
          "and data/sundance-2024/attendance.csv.\n")

    tx, ev, bars = load_phase_a()
    print(f"Loaded {len(tx)} transactions across {len(ev)} events, {len(bars)} bar-event rows.")

    tx_elapsed = build_elapsed_hours(tx, ev)
    matrix = hourly_cumulative_matrix(tx_elapsed, ev)

    q1_cumulative_curves(tx_elapsed, ev, matrix)
    q2_hourly_distribution(tx)
    summary = q3_summary_table(tx, ev)
    threshold_hour = q4_predictive_correlation(matrix, ev)
    q5_feature_audit(tx_elapsed, ev)
    q6_quality_flags(tx, ev, summary)

    h("Summary", 2)
    if threshold_hour is not None:
        print(f"Q4 answer: elapsed hour **{threshold_hour:.0f}** is where cumulative revenue "
              f"first reaches r² ≥ 0.90 against the final total (n=9, directional not robust).")
    else:
        print("Q4 answer: r² never reached 0.90 in the observed window.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
