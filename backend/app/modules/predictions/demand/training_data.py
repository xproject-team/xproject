"""Build the unified drinks-demand training grid from BOTH data sources.

Mirrors nowcast/retrain.py's shape (events_df + transactions_df pair),
extended for the extra (bar, category) dimensions this model needs.

Two sources, two different reliability profiles — see
build_demand_training_data.py (the CLI) for how they're combined:

1. HISTORICAL (2024/2025, 9 events): app.modules.predictions.nowcast
   .data/training_transactions.parquet. One row per ORDER (not line);
   `product_names` is a comma-joined string exploded here into one
   pseudo-line per item. No per-item price — irrelevant, this model's
   target is a COUNT, not revenue. Categorized via
   demand.categorize.classify_historical_product (a keyword classifier
   over the observed vocabulary, NOT the catalog join the current-year
   source gets — see that module's docstring). Bar identity does not
   transfer across events (21 distinct historical bar names, none
   matching any current-year bar) — bars are represented by RANK
   (busiest, 2nd-busiest, ...) within their own event, not by name.

2. CURRENT (2026): production customer_purchases, already exact
   (product_id-joined category, is_deposit-flagged) — see
   build_customer_features.py. Same bar-rank treatment for consistency
   with the historical source, even though literal bar_id IS known
   here; the model pools ranks across ALL training events regardless
   of source, so the representation must be uniform.

Both sources produce the same row shape:
  event_id, source, bar_rank, wall_clock_hour, hour_of_event, category,
  drinks_count
plus one row per event in the companion events table:
  event_id, source, event_date, first_order_hour, total_drinks

wall_clock_hour is the Europe/Rome clock hour (0-23) — the practical
grain a staffing decision is made in ("the 18:00 hour"). hour_of_event
is elapsed integer hours since THAT event's own first order — the
grain the shape-curve math (mirrored from nowcast/predictor.py) is fit
and indexed on, since events start at different wall-clock times and a
curve compared by raw wall-clock hour would be misaligned. Both are
kept; see predictor.py for which one each piece of math actually uses.

MAX_BAR_RANK caps the bar dimension at a fixed width regardless of how
many named bars/shops an event actually had (2026 events: ~5; some
historical events: 15+ mostly-tiny entries) — rank MAX_BAR_RANK+ is a
single pooled "everything else" bucket, keeping the pooled fit from
fragmenting into near-empty per-bar cells for events with unusually
many small stalls.
"""
from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

import pandas as pd

from app.modules.predictions.demand.categorize import classify_historical_product

ROME = ZoneInfo("Europe/Rome")
MAX_BAR_RANK = 5  # 1..4 individually, 5 = "5th-busiest-and-smaller" pooled
DRINK_CATEGORIES = ("beer", "cocktail", "spritz", "wine", "premium", "other")


@dataclass
class TrainingGrid:
    """The two DataFrames a DemandPredictor fits on. See module
    docstring for the exact column contract."""
    events: pd.DataFrame        # event_id, source, event_date, first_order_hour, total_drinks
    grid: pd.DataFrame          # event_id, source, bar_rank, wall_clock_hour, hour_of_event, category, drinks_count


def _rank_bars(volume_by_bar: pd.Series) -> dict:
    """Given a Series of {bar_key: total_volume} for ONE event, return
    {bar_key: rank} where rank 1 = highest volume, capped at MAX_BAR_RANK."""
    ordered = volume_by_bar.sort_values(ascending=False)
    ranks = {}
    for i, bar_key in enumerate(ordered.index, start=1):
        ranks[bar_key] = min(i, MAX_BAR_RANK)
    return ranks


def build_historical_grid(transactions_df: pd.DataFrame) -> TrainingGrid:
    """transactions_df: the nowcast module's training_transactions.parquet
    shape (event_id, event_date, timestamp, bar_name, product_names,
    item_count, amount_eur) — amount_eur/item_count are unused here.
    """
    rows = []
    for _, order in transactions_df.iterrows():
        names = str(order["product_names"] or "").split(",")
        for frag in names:
            frag = frag.strip()
            if not frag:
                continue
            category = classify_historical_product(frag)
            if category not in DRINK_CATEGORIES:
                continue  # excludes deposit, food, unclassified — see module docstring
            rows.append({
                "event_id": order["event_id"],
                "event_date": order["event_date"],
                "timestamp": order["timestamp"],
                "bar_name": order["bar_name"],
                "category": category,
            })
    exploded = pd.DataFrame(rows)
    return _finalize_grid(exploded, source="historical")


def build_current_grid(purchase_rows: list[dict]) -> TrainingGrid:
    """purchase_rows: dicts with event_id (str), event_date, ordered_at
    (tz-aware UTC datetime), bar_id (str), category (one of
    DRINK_CATEGORIES — food/deposit already excluded by the caller,
    see build_demand_training_data.py), qty (numeric, treated as unit
    count — always 1 in observed production data, per the Phase 1/2
    audits, but summed rather than counted rows in case that changes).
    """
    df = pd.DataFrame(purchase_rows)
    if df.empty:
        return TrainingGrid(events=pd.DataFrame(), grid=pd.DataFrame())
    df["timestamp"] = df["ordered_at"]
    df["bar_name"] = df["bar_id"]  # same "identity key within this event" role as historical bar_name
    return _finalize_grid(df, source="current")


def _finalize_grid(exploded: pd.DataFrame, *, source: str) -> TrainingGrid:
    if exploded.empty:
        return TrainingGrid(events=pd.DataFrame(), grid=pd.DataFrame())

    ts = exploded["timestamp"]
    if getattr(ts.dt, "tz", None) is not None:
        exploded["timestamp"] = ts.dt.tz_convert(ROME)
        exploded["wall_clock_hour"] = exploded["timestamp"].dt.hour
    else:
        # Historical export timestamps are naive local (Europe/Rome) —
        # the on-site POS exports carry no timezone metadata at all,
        # and the event physically happens in Rome. See module docstring.
        exploded["wall_clock_hour"] = exploded["timestamp"].dt.hour

    events_meta = []
    grid_rows = []

    for event_id, ev_group in exploded.groupby("event_id"):
        first_order_at = ev_group["timestamp"].min()
        # tz-naive-safe elapsed-hours computation
        elapsed = (ev_group["timestamp"] - first_order_at)
        ev_group = ev_group.assign(
            hour_of_event=(elapsed.dt.total_seconds() // 3600).astype(int),
        )

        bar_volume = ev_group.groupby("bar_name").size()
        ranks = _rank_bars(bar_volume)
        ev_group = ev_group.assign(bar_rank=ev_group["bar_name"].map(ranks))

        agg = (
            ev_group.groupby(["bar_rank", "wall_clock_hour", "hour_of_event", "category"])
            .size()
            .reset_index(name="drinks_count")
        )
        agg.insert(0, "event_id", event_id)
        agg.insert(1, "source", source)
        grid_rows.append(agg)

        events_meta.append({
            "event_id": event_id,
            "source": source,
            "event_date": ev_group["event_date"].iloc[0] if "event_date" in ev_group.columns else None,
            "first_order_hour": int(first_order_at.hour),
            "total_drinks": int(len(ev_group)),
        })

    events_df = pd.DataFrame(events_meta)
    grid_df = pd.concat(grid_rows, ignore_index=True) if grid_rows else pd.DataFrame()
    return TrainingGrid(events=events_df, grid=grid_df)


def build_shape_only_grid(order_rows: list[dict]) -> pd.DataFrame:
    """Build the [event_id, hour_of_event, count] table fit_demand_curves'
    `shape_only` param expects, from per-ORDER rows (not per-line).

    order_rows: dicts with event_id (str), ordered_at (tz-aware datetime —
    Slesh's created_at_slesh), count (numeric — event_orders.
    confirmed_line_count, a per-order item-count field populated
    independently of whether the order's LINES matched a product/
    stock_transaction). Built for Jul-5: see fit_demand_curves' shape_only
    docstring for why line-level exclusion doesn't block this.

    NOTE: confirmed_line_count includes food/deposit items alongside
    drinks, so this proxy's cumulative SHAPE is a close-but-imperfect
    stand-in for a drinks-only cumulative shape — validated against
    Sundance 14 (max ~4 percentage points of cumulative-fraction drift
    at the mid-event peak) before being judged usable. See retrain.py.
    """
    df = pd.DataFrame(order_rows)
    if df.empty:
        return pd.DataFrame(columns=["event_id", "hour_of_event", "count"])
    rows = []
    for event_id, g in df.groupby("event_id"):
        first_order_at = g["ordered_at"].min()
        elapsed = (g["ordered_at"] - first_order_at)
        g = g.assign(hour_of_event=(elapsed.dt.total_seconds() // 3600).astype(int))
        hourly = g.groupby("hour_of_event")["count"].sum().reset_index()
        hourly.insert(0, "event_id", event_id)
        rows.append(hourly)
    return pd.concat(rows, ignore_index=True)


def combine_grids(*grids: TrainingGrid) -> TrainingGrid:
    non_empty = [g for g in grids if not g.events.empty]
    if not non_empty:
        return TrainingGrid(events=pd.DataFrame(), grid=pd.DataFrame())
    return TrainingGrid(
        events=pd.concat([g.events for g in non_empty], ignore_index=True),
        grid=pd.concat([g.grid for g in non_empty], ignore_index=True),
    )
