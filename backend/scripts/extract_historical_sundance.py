#!/usr/bin/env python3
"""extract_historical_sundance.py — Phase A of the ML revenue-prediction
feature: build a unified training dataset from historical Sundance Slesh
exports sitting on the user's Desktop (~/Desktop/{2024,2025}/...).

THROWAWAY / OFFLINE TEST UTILITY. Not imported by the app. Read-only
against the Desktop source data; writes only to backend/scripts/ml_data/.

Usage (from backend/, so relative output paths resolve correctly):
    venv/bin/python scripts/extract_historical_sundance.py
    venv/bin/python scripts/extract_historical_sundance.py --desktop ~/Desktop

─── Source layout ───────────────────────────────────────────────────────
  ~/Desktop/2024/SUNDANCE/data_DD_MM_YYYY/{1-ricariche,2-ordini_bracciali,
      3-prodotti,4-categorie,5-negozi,6-operatori,7-bracciali,8-utenti,
      rimborsi}/*.xlsx (+ .jpg/.png dashboard screenshots, ignored)
  ~/Desktop/2025/data_DD_MM_YYYY/... (same subfolder layout, NOT nested
      under a SUNDANCE/ wrapper directory like 2024 is)

2023 is skipped (single-xlsx-per-event format, out of scope for v1).
`data_default` (empty) and `_extracted` (someone's prior pre-aggregated
CSV summaries, not raw Slesh exports) are skipped. `VIDEOCITTA` (a
different event brand entirely) is naturally excluded since it doesn't
match the `data_DD_MM_YYYY` glob.

─── Transaction grain — a deliberate, non-obvious modeling decision ────
The 2-ordini_bracciali orders file's `Prodotti` column is a
comma-joined string of every product in ONE order (e.g. "BUN manzo,
Poke pollo"), and `Totale` is the ORDER-level total — not per-product.
There is no reliable way to split that total across differently-priced
bundled products without fabricating numbers. So: one row in
transactions_df = one ORDER, `product_names` keeps the raw joined
string, `amount_eur` is the real, unmodified order total. This was
confirmed against the 5-negozi per-bar revenue summary (exact match,
to the cent) before writing this script — see the exploration report.
No `category` column: the source has no reliable per-order category
mapping (2024's category file is a single aggregate row for the whole
event; 2025's is closer but still only maps PRODUCT -> category
aggregate counts, not per-order-line).

─── Revenue filter ──────────────────────────────────────────────────────
Only Stato/status "confirmed" (2024) or "completed" (2025) rows count
as revenue — "refunded" rows are excluded, matching how 5-negozi's
official per-bar Fatturato is computed (validated: confirmed-only sum
reconciles exactly against 5-negozi in the sampled 2024 event).

─── Bar identity ────────────────────────────────────────────────────────
There is no numeric Slesh shop id anywhere in this export format —
`Negozio` is always a bare string name. bars_df is keyed on `bar_name`
(stripped of stray whitespace — 2025 has inconsistent trailing spaces
like "Cocktail Bar "), NOT a fabricated `bar_shop_id`.
"""
from __future__ import annotations

import argparse
import re
import sys
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# Order-status values that count as real revenue, per year's vocabulary.
VALID_STATUSES = {"confirmed", "completed"}

FOLDER_RE = re.compile(r"^data_(\d{2})_(\d{2})_(\d{4})$")

OUTPUT_DIR = Path(__file__).parent / "ml_data"


@dataclass
class EventExtraction:
    event_id: str
    event_date: date
    name: str
    source_folder: Path
    transactions: pd.DataFrame
    bars: pd.DataFrame
    total_revenue: float = 0.0
    first_tx_time: "datetime | None" = None
    last_tx_time: "datetime | None" = None
    unique_customers: int = 0
    transaction_count: int = 0
    refunded_count: int = 0
    recharge_total_eur: float = 0.0
    recharge_count: int = 0
    warnings: list = field(default_factory=list)


# ─── Discovery ────────────────────────────────────────────────────────

def discover_event_folders(desktop: Path) -> list[tuple[int, date, Path]]:
    """Find every real data_DD_MM_YYYY event folder under 2024/ and 2025/.

    2024's are nested under SUNDANCE/; 2025's sit directly under the
    year folder. `data_default` (empty) is skipped.
    """
    candidates: list[Path] = []
    y2024 = desktop / "2024" / "SUNDANCE"
    if y2024.is_dir():
        candidates += sorted(y2024.glob("data_*"))
    y2025 = desktop / "2025"
    if y2025.is_dir():
        candidates += sorted(y2025.glob("data_*"))

    events = []
    for folder in candidates:
        if not folder.is_dir():
            continue
        m = FOLDER_RE.match(folder.name)
        if not m:
            continue  # e.g. data_default
        dd, mm, yyyy = (int(x) for x in m.groups())
        try:
            ev_date = date(yyyy, mm, dd)
        except ValueError:
            continue
        events.append((yyyy, ev_date, folder))
    return sorted(events, key=lambda t: t[1])


# ─── File pickers (filenames carry a random export-id suffix) ──────────

def _pick_orders_file(folder: Path) -> Path | None:
    d = folder / "2-ordini_bracciali"
    if not d.is_dir():
        return None
    matches = [f for f in d.glob("*.xlsx") if "order" in f.name.lower()]
    return matches[0] if matches else None


def _pick_negozi_file(folder: Path) -> Path | None:
    d = folder / "5-negozi"
    if not d.is_dir():
        return None
    matches = list(d.glob("*.xlsx"))
    return matches[0] if matches else None


def _pick_ricariche_file(folder: Path) -> Path | None:
    """The raw per-recharge list, NOT the 'Split ricariche per giorno'
    daily-aggregate file."""
    d = folder / "1-ricariche"
    if not d.is_dir():
        return None
    matches = [f for f in d.glob("*.xlsx") if "split" not in f.name.lower()]
    return matches[0] if matches else None


# ─── Per-event extraction ───────────────────────────────────────────────

def extract_event(yyyy: int, ev_date: date, folder: Path) -> EventExtraction:
    event_id = f"sundance_{ev_date.isoformat()}"
    name = f"Sundance {ev_date.strftime('%d/%m/%Y')}"
    warn: list[str] = []

    orders_path = _pick_orders_file(folder)
    if orders_path is None:
        raise ValueError(f"no orders xlsx found under {folder}/2-ordini_bracciali")

    orders = pd.read_excel(orders_path)
    required_cols = {"Data ed ora", "Negozio", "Prodotti", "Totale", "Stato", "ID utente"}
    missing = required_cols - set(orders.columns)
    if missing:
        raise ValueError(f"orders file {orders_path.name} missing columns: {missing}")

    orders["bar_name"] = orders["Negozio"].astype(str).str.strip()
    orders["timestamp"] = pd.to_datetime(
        orders["Data ed ora"], format="%d/%m/%Y %H:%M", errors="coerce",
    )
    bad_ts = orders["timestamp"].isna().sum()
    if bad_ts:
        warn.append(f"{bad_ts} row(s) with unparseable timestamp — dropped")
        orders = orders.dropna(subset=["timestamp"])

    # Sanity check: the export filename encodes an event date (e.g.
    # "...-slesh-...xlsx" living under data_04_08_2024), but filenames
    # have been found to be WRONG — a duplicate/mislabeled export (see
    # sundance_2024-08-04, byte-identical to sundance_2024-07-28's file,
    # confirmed via md5). If the actual row timestamps don't fall on the
    # folder's claimed date, this is that bug — reject rather than
    # silently double-count one real event as two.
    tx_dates = orders["timestamp"].dt.date.value_counts()
    if len(tx_dates) and tx_dates.idxmax() != ev_date:
        raise ValueError(
            f"orders file claims date {ev_date.isoformat()} but {tx_dates.max()} of "
            f"{len(orders)} rows are actually dated {tx_dates.idxmax().isoformat()} — "
            f"likely a duplicate/mislabeled export (see the 2024-08-04/2024-07-28 "
            f"byte-identical file bug found during exploration)"
        )

    status_lower = orders["Stato"].astype(str).str.lower()
    refunded_count = int((~status_lower.isin(VALID_STATUSES)).sum())
    valid = orders[status_lower.isin(VALID_STATUSES)].copy()

    valid["item_count"] = valid["Prodotti"].astype(str).str.split(",").apply(len)

    transactions = pd.DataFrame({
        "event_date": ev_date,
        "event_id": event_id,
        "timestamp": valid["timestamp"],
        "bar_name": valid["bar_name"],
        "product_names": valid["Prodotti"].astype(str),
        "item_count": valid["item_count"].astype("int32"),
        "amount_eur": valid["Totale"].astype(float),
    }).reset_index(drop=True)

    # ── Bars — from the 5-negozi reconciliation summary when available,
    # falling back to a group-by of the transactions themselves.
    negozi_path = _pick_negozi_file(folder)
    tx_by_bar = transactions.groupby("bar_name")["amount_eur"].agg(["sum", "count"])
    tx_by_bar.columns = ["tx_revenue_eur", "tx_count"]

    if negozi_path is not None:
        negozi = pd.read_excel(negozi_path)
        negozi["bar_name"] = negozi["Negozio"].astype(str).str.strip()
        negozi = negozi.set_index("bar_name")
        bars = negozi[["Quantità", "Fatturato"]].rename(
            columns={"Quantità": "reported_quantity", "Fatturato": "reported_revenue_eur"},
        ).join(tx_by_bar, how="outer")
        # Reconciliation check: reported (5-negozi) vs. what we actually
        # summed from orders. A small gap (~<2%) on drink-serving bars is
        # EXPECTED and understood — 5-negozi's Fatturato includes glass
        # deposit (cauzione) charges that orders.Totale does not, and the
        # gap on a sampled 2025 event matched the "Rimborsato" (returned
        # deposit) count from the cauzione file exactly. Only flag gaps
        # bigger than that as a real problem.
        gap = (bars["reported_revenue_eur"].fillna(0) - bars["tx_revenue_eur"].fillna(0))
        pct_gap = (gap.abs() / bars["reported_revenue_eur"].replace(0, pd.NA)).fillna(0)
        real_mismatch = pct_gap > 0.02
        if real_mismatch.any():
            bad_bars = bars.index[real_mismatch].tolist()
            warn.append(
                f"revenue mismatch >2% vs 5-negozi for bar(s) {bad_bars} — "
                f"NOT the known cauzione gap, needs a look"
            )
        elif gap.abs().sum() > 0.01:
            warn.append(
                f"minor revenue gap vs 5-negozi (€{gap.abs().sum():.2f} total, <2% per bar) — "
                f"consistent with the known cauzione/deposit timing difference, not flagged as an error"
            )
    else:
        warn.append("no 5-negozi file found — bars_df built from transactions only, no reconciliation")
        bars = tx_by_bar.rename(columns={"tx_revenue_eur": "reported_revenue_eur"})
        bars["reported_quantity"] = pd.NA

    bars = bars.reset_index().rename(columns={"index": "bar_name"})
    bars.insert(0, "event_id", event_id)
    bars.insert(0, "event_date", ev_date)

    # ── Recharges (1-ricariche) — feature: recharge velocity predicts revenue.
    recharge_total = 0.0
    recharge_count = 0
    ricariche_path = _pick_ricariche_file(folder)
    if ricariche_path is not None:
        try:
            ricariche = pd.read_excel(ricariche_path)
            if "Totale" in ricariche.columns:
                recharge_total = float(ricariche["Totale"].sum())
                recharge_count = int(len(ricariche))
        except Exception as exc:  # noqa: BLE001 — one bad file shouldn't kill the event
            warn.append(f"could not parse ricariche file: {exc}")
    else:
        warn.append("no 1-ricariche (non-split) file found")

    return EventExtraction(
        event_id=event_id,
        event_date=ev_date,
        name=name,
        source_folder=folder,
        transactions=transactions,
        bars=bars,
        total_revenue=float(transactions["amount_eur"].sum()),
        first_tx_time=transactions["timestamp"].min() if len(transactions) else None,
        last_tx_time=transactions["timestamp"].max() if len(transactions) else None,
        unique_customers=int(valid["ID utente"].nunique()),
        transaction_count=len(transactions),
        refunded_count=refunded_count,
        recharge_total_eur=recharge_total,
        recharge_count=recharge_count,
        warnings=warn,
    )


# ─── Orchestration ────────────────────────────────────────────────────

def run(desktop: Path) -> int:
    found = discover_event_folders(desktop)
    if not found:
        print(f"No event folders found under {desktop}/2024 or {desktop}/2025", file=sys.stderr)
        return 1

    print(f"Discovered {len(found)} event folder(s):")
    for yyyy, ev_date, folder in found:
        print(f"  {ev_date.isoformat()}  {folder}")
    print()

    extractions: list[EventExtraction] = []
    skipped: list[tuple[Path, str]] = []
    for yyyy, ev_date, folder in found:
        try:
            ext = extract_event(yyyy, ev_date, folder)
            extractions.append(ext)
        except Exception as exc:  # noqa: BLE001 — one bad event shouldn't kill the run
            skipped.append((folder, str(exc)))
            print(f"SKIPPED {folder.name}: {exc}")

    if not extractions:
        print("Nothing extracted — aborting.", file=sys.stderr)
        return 1

    transactions_df = pd.concat([e.transactions for e in extractions], ignore_index=True)
    bars_df = pd.concat([e.bars for e in extractions], ignore_index=True)
    events_df = pd.DataFrame([{
        "event_date": e.event_date,
        "event_id": e.event_id,
        "name": e.name,
        "total_revenue": e.total_revenue,
        "first_tx_time": e.first_tx_time,
        "last_tx_time": e.last_tx_time,
        "unique_customers": e.unique_customers,
        "transaction_count": e.transaction_count,
        "refunded_count": e.refunded_count,
        "recharge_total_eur": e.recharge_total_eur,
        "recharge_count": e.recharge_count,
        "bar_count": e.bars["bar_name"].nunique(),
        "source_folder": str(e.source_folder),
    } for e in extractions])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tx_path = OUTPUT_DIR / "training_transactions.parquet"
    ev_path = OUTPUT_DIR / "training_events.parquet"
    bar_path = OUTPUT_DIR / "training_bars.parquet"
    transactions_df.to_parquet(tx_path, index=False)
    events_df.to_parquet(ev_path, index=False)
    bars_df.to_parquet(bar_path, index=False)

    # ─── Sanity checks ───────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SANITY CHECKS")
    print("=" * 70)
    print(f"Events extracted: {len(extractions)} (of {len(found)} folders found)")
    print(f"Total transactions: {len(transactions_df)}")
    print(f"Total revenue (all events): €{transactions_df['amount_eur'].sum():,.2f}")
    print()
    print(f"{'event_id':<22} {'date':<12} {'tx_count':>9} {'revenue_eur':>13} "
          f"{'refunded':>9} {'first_tx':>17} {'last_tx':>17}")
    flagged = []
    notes = []
    for e in extractions:
        print(f"{e.event_id:<22} {e.event_date.isoformat():<12} {e.transaction_count:>9} "
              f"{e.total_revenue:>13,.2f} {e.refunded_count:>9} "
              f"{str(e.first_tx_time):>17} {str(e.last_tx_time):>17}")
        if e.transaction_count == 0:
            flagged.append((e.event_id, "0 transactions"))
        if e.total_revenue < 0:
            flagged.append((e.event_id, "negative revenue"))
        for w in e.warnings:
            (flagged if "NOT the known cauzione gap" in w else notes).append((e.event_id, w))

    if flagged:
        print("\nFLAGGED (needs a look):")
        for eid, reason in flagged:
            print(f"  {eid}: {reason}")
    else:
        print("\nNo events flagged as corrupt.")

    if notes:
        print("\nNOTES (informational, not treated as errors):")
        for eid, reason in notes:
            print(f"  {eid}: {reason}")

    if skipped:
        print("\nSKIPPED (unreadable/corrupt):")
        for folder, reason in skipped:
            print(f"  {folder}: {reason}")

    print()
    print(f"Wrote {tx_path} ({tx_path.stat().st_size:,} bytes)")
    print(f"Wrote {ev_path} ({ev_path.stat().st_size:,} bytes)")
    print(f"Wrote {bar_path} ({bar_path.stat().st_size:,} bytes)")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop", default="~/Desktop", help="Path to the Desktop folder (default ~/Desktop)")
    args = parser.parse_args()
    return run(Path(args.desktop).expanduser())


if __name__ == "__main__":
    raise SystemExit(main())
