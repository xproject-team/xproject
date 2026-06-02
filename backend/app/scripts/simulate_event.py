"""Replay a real Slesh event export against a live xproject event.

Drives StockTransactions through the service layer from the
2025 Slesh XLSX exports. Used for end-to-end dry-runs ahead of
Sundance 2026.

Usage:
    python -m app.scripts.simulate_event \\
        --event-id 76fa15a9-... \\
        --data-dir ~/Desktop/2025/data_15_06_2025 \\
        --limit 5 \\
        --speed-x 60

Args:
    --event-id   Target LIVE event UUID (must be seeded — see
                 seed_sim_event.py).
    --data-dir   Path to a data_DD_MM_YYYY folder containing
                 2-ordini_bracciali/ and 3-prodotti/ subdirs.
    --limit N    Process only first N orders. Default: all 4,224.
    --speed-x F  Time compression. 60 = 10h event in 10 min.
                 0 = no sleeps (as fast as possible). Default: 0.
    --dry-run    Parse + plan, but don\'t write to DB.

S5 of docs/e2e-validation-design.md.
"""
import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import openpyxl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
# Import app.main to wake the full SQLAlchemy mapper registry.
# StockTransaction has FKs to tenants, events, bars, products,
# bar_stock, and (self-referentially) stock_transactions, plus the
# parent_transaction_id chain. Importing each individually risks
# missing one (we discovered this the hard way). app.main pulls
# every module in.
import app.main  # noqa: F401

from app.modules.bars.models import Bar
from app.modules.events.models import Event, EventStatus
from app.modules.products.models import Product, ProductType
from app.modules.stock_transactions.models import (
    PaymentType, StockTransaction, TransactionSource,
)
from app.modules.stock_transactions.schemas import (
    ManualAdjustmentRequest, SaleIngestRequest,
)
from app.modules.stock_transactions.service import StockTransactionService


# ─── Data classes ─────────────────────────────────────────────────────

@dataclass
class SimOrder:
    """One row from experience-orders XLSX, normalized."""
    slesh_id:      str        # Mongo ObjectID, e.g. "684ea46bb1fc6f768d25a954"
    seq:           int        # parsed from "el-N" Codice column
    timestamp:     datetime   # parsed from "Data ed ora"
    shop_name:     str        # "Negozio", stripped
    products:      list[str]  # split "Prodotti" by ", "
    totale_eur:    Decimal    # "Totale" column (whole EUR per export)


# ─── Loaders ──────────────────────────────────────────────────────────

def _parse_codice_seq(codice: str) -> int:
    """\"el-0\" -> 0, \"el-1099\" -> 1099. Used for stable ordering
    (timestamp has only minute precision; sub-minute order is needed)."""
    if codice is None or not codice.startswith("el-"):
        return -1
    try:
        return int(codice[3:])
    except ValueError:
        return -1


def _parse_data_ed_ora(s: str) -> datetime:
    """\"15/06/2025 12:46\" -> datetime (naive, no tz info)."""
    return datetime.strptime(s, "%d/%m/%Y %H:%M")


def load_orders(data_dir: Path) -> list[SimOrder]:
    """Read experience-orders-*.xlsx from data_dir/2-ordini_bracciali/."""
    subdir = data_dir / "2-ordini_bracciali"
    xlsx_files = sorted(subdir.glob("experience-orders-*.xlsx"))
    if not xlsx_files:
        print(f"❌ no experience-orders xlsx in {subdir}", file=sys.stderr)
        sys.exit(1)
    f = xlsx_files[0]
    print(f"  reading {f.name}")
    wb = openpyxl.load_workbook(f, read_only=True)
    ws = wb.active

    orders: list[SimOrder] = []
    skipped_not_experience = 0
    skipped_not_completed = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        # Cols: 0=ID 1=Data 2=Codice 3=Negozio 4=Prodotti 5=Totale
        #       6=Stato 7=Tipologia 8-17=user metadata (ignored)
        if row[0] is None:
            continue
        if row[7] != "experience":
            skipped_not_experience += 1
            continue
        if row[6] != "completed":
            skipped_not_completed += 1
            continue

        products_raw = row[4]
        products = [
            p.strip() for p in str(products_raw).split(",") if p.strip()
        ] if products_raw else []

        orders.append(SimOrder(
            slesh_id=str(row[0]),
            seq=_parse_codice_seq(row[2]),
            timestamp=_parse_data_ed_ora(str(row[1])),
            shop_name=str(row[3]).strip(),
            products=products,
            totale_eur=Decimal(str(row[5] or 0)),
        ))
    wb.close()

    if skipped_not_experience or skipped_not_completed:
        print(f"  skipped: {skipped_not_experience} non-experience, "
              f"{skipped_not_completed} non-completed")
    orders.sort(key=lambda o: o.seq)
    print(f"  loaded {len(orders)} orders ordered by Codice seq")
    return orders


# ─── Pre-flight checks ────────────────────────────────────────────────

async def preflight(
    db: AsyncSession, event_id: UUID,
) -> tuple[Event, dict[str, Bar], dict[str, Product]]:
    """Verify the target event is LIVE and build name → ID maps."""
    event = await db.get(Event, event_id)
    if event is None:
        raise RuntimeError(f"event {event_id} not found")
    if event.status != EventStatus.LIVE:
        raise RuntimeError(
            f"event {event_id} is {event.status.value}, must be LIVE"
        )

    # Bars in this event, indexed by normalized name
    r = await db.execute(select(Bar).where(Bar.event_id == event.id))
    bars = list(r.scalars().all())
    bars_by_name = {_norm(b.name): b for b in bars}
    print(f"  event LIVE ({event.name}), {len(bars)} bars")

    # Products for this tenant
    r = await db.execute(select(Product).where(Product.tenant_id == event.tenant_id))
    products = list(r.scalars().all())
    products_by_name = {_norm(p.name): p for p in products}
    print(f"  {len(products)} products in tenant catalog")

    return event, bars_by_name, products_by_name


def _norm(s: str) -> str:
    """Same normalization as proposals_service._best_fuzzy_match: lowercase
    + collapse internal whitespace + strip."""
    return " ".join(s.lower().split())


# ─── Simulator core ───────────────────────────────────────────────────

@dataclass
class SimStats:
    orders_processed:       int = 0
    tx_created:             int = 0
    drinks_ingested:        int = 0     # via ingest_sale (drinks)
    food_adjusted:          int = 0     # via record_adjustment (food/supply)
    idempotency_replays:    int = 0     # ingest_sale found existing tx
    skipped_unknown_bar:    int = 0
    skipped_unknown_prod:   int = 0
    ingestion_errors:       int = 0
    errors:                 list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


async def run_simulation(
    *,
    event_id: UUID,
    data_dir: Path,
    limit: int | None,
    speed_x: float,
    dry_run: bool,
) -> SimStats:
    """Main simulator loop."""
    stats = SimStats()

    orders = load_orders(data_dir)
    if limit is not None:
        orders = orders[:limit]
        print(f"  --limit {limit}: processing first {len(orders)} only")

    async with AsyncSessionLocal() as db:
        event, bars_by_name, products_by_name = await preflight(db, event_id)

        # Construct service ONCE; reuse for every line.
        service = StockTransactionService(db)

        sim_run_id = uuid4().hex[:8]  # collision-safe per sim run
        print(f"  sim_run_id={sim_run_id}  dry_run={dry_run}  speed_x={speed_x}")
        print()
        print("─── streaming orders ───")

        prev_ts = orders[0].timestamp if orders else None
        for o in orders:
            # Time-compression sleep
            if speed_x > 0 and prev_ts is not None:
                delta_secs = (o.timestamp - prev_ts).total_seconds()
                if delta_secs > 0:
                    await asyncio.sleep(delta_secs / speed_x)
            prev_ts = o.timestamp

            # Resolve bar
            bar = bars_by_name.get(_norm(o.shop_name))
            if bar is None:
                stats.skipped_unknown_bar += 1
                msg = f"  ⚠️  order seq={o.seq}: unknown bar {o.shop_name!r}"
                if stats.skipped_unknown_bar <= 5:
                    print(msg)
                continue

            # Each product line becomes one transaction via the SERVICE
            # layer (NOT raw INSERT). This exercises the full pipeline:
            # bar_stock decrement, recipe cascade (drinks), idempotency,
            # realtime publish. Drinks → ingest_sale, Food/Supply →
            # record_adjustment (ingest_sale rejects non-drinks).
            for idx, prod_name in enumerate(o.products):
                product = products_by_name.get(_norm(prod_name))
                if product is None:
                    stats.skipped_unknown_prod += 1
                    msg = (f"  ⚠️  order seq={o.seq}: unknown product "
                           f"{prod_name!r} (bar={o.shop_name!r})")
                    if stats.skipped_unknown_prod <= 5:
                        print(msg)
                    continue

                if dry_run:
                    stats.tx_created += 1
                    continue

                price_cents = (
                    product.default_price_cents
                    if product.default_price_cents is not None
                    else int(round(float(o.totale_eur) * 100 / max(1, len(o.products))))
                )
                idempotency_key = f"sim-{sim_run_id}-{o.seq}-{idx}"

                try:
                    if product.product_type == ProductType.DRINK:
                        # Drinks: full Slesh-POS cascade via ingest_sale.
                        result = await service.ingest_sale(
                            event.tenant_id,
                            SaleIngestRequest(
                                event_id=event.id,
                                bar_id=bar.id,
                                product_id=product.id,
                                qty=Decimal("1"),
                                price_cents=price_cents,
                                source=TransactionSource.SLESH_POS,
                                payment_type=PaymentType.TOKEN,  # Sundance NFC
                                source_idempotency_key=idempotency_key,
                            ),
                        )
                        if result.idempotency_replay:
                            stats.idempotency_replays += 1
                        else:
                            stats.drinks_ingested += 1
                            stats.tx_created += 1
                    else:
                        # Food + supply: write standalone ledger row.
                        # ingest_sale rejects non-drinks; use the adjustment
                        # path with MANUAL_ADJUSTMENT source.
                        await service.record_adjustment(
                            event.tenant_id,
                            ManualAdjustmentRequest(
                                event_id=event.id,
                                bar_id=bar.id,
                                product_id=product.id,
                                qty=Decimal("1"),
                                source=TransactionSource.MANUAL_ADJUSTMENT,
                                note=(f"simulator replay: 2025-06-15 "
                                      f"el-{o.seq} line {idx} "
                                      f"({product.product_type.value})"),
                            ),
                        )
                        stats.food_adjusted += 1
                        stats.tx_created += 1
                except Exception as e:
                    stats.ingestion_errors += 1
                    if stats.ingestion_errors <= 5:
                        print(f"  ❌ ingest seq={o.seq} idx={idx} "
                              f"product={prod_name!r}: {type(e).__name__}: {e}")
                    stats.errors.append(
                        f"seq={o.seq}/idx={idx}/{prod_name!r}: {type(e).__name__}"
                    )

            stats.orders_processed += 1

            # Progress every 200 tx (no manual flush — service commits)
            if stats.tx_created > 0 and stats.tx_created % 200 == 0:
                print(f"  [progress] orders={stats.orders_processed} "
                      f"tx={stats.tx_created} (drinks={stats.drinks_ingested} "
                      f"food={stats.food_adjusted} "
                      f"replays={stats.idempotency_replays} "
                      f"errors={stats.ingestion_errors})")

        # NOTE: no outer commit — each service call commits internally.

    return stats


# ─── CLI ──────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Replay a Slesh event export.")
    p.add_argument("--event-id", required=True, type=UUID)
    p.add_argument("--data-dir", required=True, type=Path)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--speed-x", type=float, default=0,
                   help="Time compression. 60=10h in 10min. 0=no sleep.")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


async def main():
    args = parse_args()
    data_dir = args.data_dir.expanduser()
    print(f"═══ Simulator ═══")
    print(f"  event_id: {args.event_id}")
    print(f"  data_dir: {data_dir}")
    print(f"  limit:    {args.limit or '(all)'}")
    print(f"  speed_x:  {args.speed_x}")
    print(f"  dry_run:  {args.dry_run}")
    print()
    stats = await run_simulation(
        event_id=args.event_id,
        data_dir=data_dir,
        limit=args.limit,
        speed_x=args.speed_x,
        dry_run=args.dry_run,
    )
    print()
    print(f"═══ Done ═══")
    print(f"  orders_processed:     {stats.orders_processed}")
    print(f"  tx_created:           {stats.tx_created}")
    print(f"    drinks_ingested:    {stats.drinks_ingested}")
    print(f"    food_adjusted:      {stats.food_adjusted}")
    print(f"    idempotency_replays:{stats.idempotency_replays}")
    print(f"  skipped_unknown_bar:  {stats.skipped_unknown_bar}")
    print(f"  skipped_unknown_prod: {stats.skipped_unknown_prod}")
    print(f"  ingestion_errors:    {stats.ingestion_errors}")
    if stats.errors:
        print(f"  errors ({len(stats.errors)}):")
        for e in stats.errors[:10]:
            print(f"    {e}")


if __name__ == "__main__":
    asyncio.run(main())
