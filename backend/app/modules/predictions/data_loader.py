"""Shared Slesh historical-event data loader for ML training + prediction.

ONE source of truth for how we read the data/ folder. All ML code
(training notebooks, MLPredictor, Revenue Anomaly backtest) imports
from here. Inline parsing is forbidden — drift between scripts is
how the rain event silently leaked into training during the v1
proof-of-concept.

Spec: docs/predictions-module-spec.md §4.2 (training data contract).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

# Path is relative to repo root.  Caller must `cd` into the repo or
# pass an explicit data_root.
DATA_ROOT_DEFAULT = Path("data/2025/SUNDANCE")

# July 13 is the rain-outlier event Omar confirmed (PDF response,
# April 2026).  Held out of training per May 27 ML design decision.
RAIN_OUTLIER_DATES: frozenset[str] = frozenset({"2025-07-13"})

# Columns we DROP at load time — PII or duplicate.
PII_COLUMNS = (
    "Nome", "Cognome", "Email", "Email utente", "Genere",
    "ID utente", "Utente",  # user identity
)

# Italian → English column rename map (kept short, only what we use).
RENAME = {
    "Data ed ora":             "ts",
    "Negozio":                 "bar",
    "Prodotti":                "products",
    "Totale":                  "revenue",
    "Stato":                   "status",
    "Tipologia":               "order_type",
    "Totale Cauzioni":         "deposit_total",
    "Codice":                  "operator_code",
}


@dataclass(frozen=True)
class EventData:
    """One historical Slesh event, cleaned + ready for modeling."""

    event_date: datetime          # parsed from folder name
    raw_orders: pd.DataFrame      # one row per completed order
    hourly: pd.DataFrame          # per (hour × bar) aggregation
    is_rain_outlier: bool         # True for 2025-07-13


def _parse_event_date(folder_name: str) -> datetime:
    """Folder name is e.g. \"data_03_08_2025\" → 2025-08-03."""
    # data_DD_MM_YYYY  →  year-month-day
    parts = folder_name.replace("data_", "").split("_")
    if len(parts) != 3:
        raise ValueError(f"unparseable event folder: {folder_name}")
    dd, mm, yyyy = parts
    return datetime(int(yyyy), int(mm), int(dd))


def _load_orders_xlsx(event_dir: Path) -> pd.DataFrame:
    """Read the experience-orders xlsx, parse timestamp DD/MM correctly."""
    orders_dir = event_dir / "2-ordini_bracliali"
    # ↑ defensive: the actual folder is "2-ordini_bracciali" (two c's).
    # Slesh's export typo, kept as-is to match disk.  Tolerate either.
    if not orders_dir.exists():
        orders_dir = event_dir / "2-ordini_bracciali"
    if not orders_dir.exists():
        raise FileNotFoundError(f"no orders folder under {event_dir}")

    xlsxs = list(orders_dir.glob("*.xlsx"))
    if not xlsxs:
        raise FileNotFoundError(f"no .xlsx under {orders_dir}")
    # Take the first (Slesh exports one per event).
    df = pd.read_excel(xlsxs[0])

    # Drop PII columns that exist.
    cols_to_drop = [c for c in PII_COLUMNS if c in df.columns]
    df = df.drop(columns=cols_to_drop)

    # Rename Italian → English (only known cols).
    df = df.rename(columns=RENAME)

    # Parse timestamp with dayfirst=True (DD/MM/YYYY HH:MM).
    df["ts"] = pd.to_datetime(df["ts"], dayfirst=True, errors="coerce")

    # Filter to completed only (drops cancelled, refunded, etc.).
    if "status" in df.columns:
        df = df[df["status"] == "completed"].copy()

    # Strip trailing whitespace on bar names ("Cocktail Bar " bug).
    if "bar" in df.columns:
        df["bar"] = df["bar"].str.strip()

    return df.reset_index(drop=True)


def _aggregate_hourly(orders: pd.DataFrame) -> pd.DataFrame:
    """Per (hour × bar): revenue sum + order count."""
    if orders.empty:
        return pd.DataFrame(
            columns=["hour", "bar", "revenue", "order_count"]
        )
    df = orders.copy()
    df["hour"] = df["ts"].dt.floor("h")  # h = hour bucket
    agg = (
        df.groupby(["hour", "bar"], as_index=False)
          .agg(revenue=("revenue", "sum"),
               order_count=("revenue", "size"))
          .sort_values(["hour", "bar"])
          .reset_index(drop=True)
    )
    return agg


def load_event(event_dir: Path) -> EventData:
    """Load + clean one event folder."""
    event_date = _parse_event_date(event_dir.name)
    raw = _load_orders_xlsx(event_dir)
    hourly = _aggregate_hourly(raw)
    is_rain = event_date.strftime("%Y-%m-%d") in RAIN_OUTLIER_DATES
    return EventData(
        event_date=event_date,
        raw_orders=raw,
        hourly=hourly,
        is_rain_outlier=is_rain,
    )


def load_all_events(
    data_root: Path = DATA_ROOT_DEFAULT,
    *,
    exclude_outliers: bool = True,
) -> list[EventData]:
    """Load every event folder under data_root.

    By default the rain outlier (2025-07-13) is excluded — that\'s the
    training-set behavior. Pass exclude_outliers=False to get all events
    (for the demo \"what would the system have predicted for the rain
    day?\" backtest).
    """
    if not data_root.exists():
        raise FileNotFoundError(f"no data root at {data_root}")
    events: list[EventData] = []
    for sub in sorted(data_root.iterdir()):
        if sub.is_dir() and sub.name.startswith("data_"):
            ev = load_event(sub)
            if exclude_outliers and ev.is_rain_outlier:
                continue
            events.append(ev)
    return events


if __name__ == "__main__":
    # Smoke test when run directly: python -m app.modules.predictions.data_loader
    events = load_all_events(exclude_outliers=False)
    print(f"Loaded {len(events)} events:")
    for ev in events:
        rain = " (RAIN OUTLIER)" if ev.is_rain_outlier else ""
        print(
            f"  {ev.event_date.date()}  "
            f"raw={len(ev.raw_orders):>5} orders,  "
            f"hourly={len(ev.hourly):>3} buckets"
            f"{rain}"
        )
