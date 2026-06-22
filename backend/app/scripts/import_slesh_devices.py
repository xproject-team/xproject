#!/usr/bin/env python3
"""
Import Slesh per-operator Excel exports into bar_devices,
recharge_stations, recharge_devices, and ricarica_transactions.

Reads two Slesh exports:
  --fatturato  fatturato_per_operatore_*.xlsx  (revenue per operator)
  --ricariche  ricaricato_per_operatore_*.xlsx (recharges per operator)

For each device row in fatturato, creates/updates a bar_devices row.
For each device row in ricariche, creates a recharge_devices row plus
aggregate ricarica_transactions rows for the payment-method sub-rows.

Idempotent: re-running with the same Excel files replaces all
recharge_stations / recharge_devices / ricarica_transactions for the
event (clean wipe + insert), and UPSERTs bar_devices (preserving any
ingester-written fields like last_order_at).

Usage:
    python -m app.scripts.import_slesh_devices \\
        --event-id 6bd035a9-3ab4-4c7f-8f68-c811aef9fa47 \\
        --tenant-id 25ef916c-a288-44ae-b17c-8dfd09390834 \\
        --fatturato /path/to/fatturato_per_operatore_xxx.xlsx \\
        --ricariche /path/to/ricaricato_per_operatore_xxx.xlsx \\
        --dry-run
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.core.config import settings  # noqa: E402


OPERATOR_RE = re.compile(r"^(.+?)\s+Operator\s+(\d+)\s*$", re.IGNORECASE)

PAYMENT_MAP = {
    "stripe ttp": "stripe_ttp",
    "contanti":   "contanti",
    "crediti":    "crediti",
    "pos":        "pos",
}


def parse_operator(s: str):
    """Parse 'Ss-bar-main Operator 4' -> ('Ss-bar-main', 4). None if no match."""
    m = OPERATOR_RE.match(s.strip())
    if not m:
        return None
    return m.group(1).strip(), int(m.group(2))


def email_from(prefix: str, number: int) -> str:
    """Build slesh_operator_email like 'Ss-bar-main-4@slesh.it'."""
    return f"{prefix}-{number}@slesh.it"


def normalize_payment(s: str) -> str:
    """Normalize Excel payment label (e.g. 'Stripe TTP' -> 'stripe_ttp')."""
    key = s.strip().lower()
    return PAYMENT_MAP.get(key, key.replace(" ", "_").replace("&", "_"))


async def run(event_id, tenant_id, fatturato_path, ricariche_path, dry_run):
    print(f"=== Slesh Device Import ===")
    print(f"  event_id:   {event_id}")
    print(f"  tenant_id:  {tenant_id}")
    print(f"  fatturato:  {fatturato_path}")
    print(f"  ricariche:  {ricariche_path}")
    print(f"  dry_run:    {dry_run}")

    df_fat = pd.read_excel(fatturato_path)
    df_ric = pd.read_excel(ricariche_path)

    bar_rows = df_fat[df_fat["Negozi"].notna()].copy()
    print(f"\nParsed {len(bar_rows)} bar device rows from fatturato")

    url = settings.database_url.replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
    eng = create_async_engine(url)

    async with eng.connect() as conn:
        trans = await conn.begin()
        try:
            r = await conn.execute(
                text("""
                    SELECT id, name FROM bars
                    WHERE tenant_id = CAST(:t AS uuid)
                      AND event_id  = CAST(:e AS uuid)
                """),
                {"t": tenant_id, "e": event_id},
            )
            bars_by_name = {row.name: str(row.id) for row in r}
            print(f"\nBars at this event ({len(bars_by_name)}):")
            for n, bid in bars_by_name.items():
                print(f"  {n:20} -> {bid}")

            excel_bar_names = set(bar_rows["Negozi"].unique())
            missing = excel_bar_names - set(bars_by_name)
            if missing:
                raise RuntimeError(
                    f"Excel references bars not in DB for this event: {missing}"
                )

            await conn.execute(
                text("DELETE FROM recharge_stations WHERE event_id = CAST(:e AS uuid)"),
                {"e": event_id},
            )

            print("\n=== bar_devices ===")
            for _, row in bar_rows.iterrows():
                parsed = parse_operator(str(row["Operatore"]))
                if not parsed:
                    op_val = row["Operatore"]
                    print(f"  SKIP: {op_val!r}")
                    continue
                prefix, number = parsed
                email = email_from(prefix, number)
                bar_id = bars_by_name[str(row["Negozi"])]

                await conn.execute(
                    text("""
                        INSERT INTO bar_devices (
                            id, tenant_id, event_id, bar_id,
                            slesh_operator_id, slesh_operator_email,
                            device_number, role
                        ) VALUES (
                            gen_random_uuid(),
                            CAST(:t AS uuid), CAST(:e AS uuid), CAST(:b AS uuid),
                            :sid, :email, :num, 'bartender'
                        )
                        ON CONFLICT (event_id, slesh_operator_id) DO UPDATE SET
                            slesh_operator_email = EXCLUDED.slesh_operator_email,
                            device_number = EXCLUDED.device_number,
                            updated_at = now()
                    """),
                    {"t": tenant_id, "e": event_id, "b": bar_id,
                     "sid": email, "email": email, "num": number},
                )
                neg_name = row["Negozi"]
                print(f"  {neg_name:20} {email}")

            print("\n=== recharge_station + devices + transactions ===")
            r = await conn.execute(
                text("""
                    INSERT INTO recharge_stations (id, tenant_id, event_id, name)
                    VALUES (gen_random_uuid(), CAST(:t AS uuid), CAST(:e AS uuid),
                            'Recharge Desk')
                    RETURNING id
                """),
                {"t": tenant_id, "e": event_id},
            )
            station_id = str(r.scalar())
            print(f"  station: {station_id}")

            current_device_id = None
            n_devices, n_txs, total_cents = 0, 0, 0
            for _, row in df_ric.iterrows():
                op_str = str(row["Operatore"]).strip()
                parsed = parse_operator(op_str)
                if parsed:
                    prefix, number = parsed
                    email = email_from(prefix, number)
                    r = await conn.execute(
                        text("""
                            INSERT INTO recharge_devices (
                                id, tenant_id, event_id, recharge_station_id,
                                slesh_operator_id, slesh_operator_email,
                                device_number, role
                            ) VALUES (
                                gen_random_uuid(),
                                CAST(:t AS uuid), CAST(:e AS uuid), CAST(:s AS uuid),
                                :sid, :email, :num, 'cashier'
                            )
                            RETURNING id
                        """),
                        {"t": tenant_id, "e": event_id, "s": station_id,
                         "sid": email, "email": email, "num": number},
                    )
                    current_device_id = str(r.scalar())
                    n_devices += 1
                    print(f"  device {email}")
                else:
                    if current_device_id is None:
                        continue
                    payment = normalize_payment(op_str)
                    trans_count = int(row["Transazioni"])
                    amount_eur = float(row["Ricaricato"])
                    amount_cents = int(round(amount_eur * 100))

                    await conn.execute(
                        text("""
                            INSERT INTO ricarica_transactions (
                                id, tenant_id, event_id, recharge_device_id,
                                amount_cents, transaction_count, payment_method, source
                            ) VALUES (
                                gen_random_uuid(),
                                CAST(:t AS uuid), CAST(:e AS uuid), CAST(:d AS uuid),
                                :amt, :cnt, :pay, 'slesh_export'
                            )
                        """),
                        {"t": tenant_id, "e": event_id, "d": current_device_id,
                         "amt": amount_cents, "cnt": trans_count, "pay": payment},
                    )
                    total_cents += amount_cents
                    n_txs += 1
                    print(f"    -> {payment}: {trans_count} tx, EUR {amount_eur:,.2f}")

            print(f"\n  {n_devices} recharge_devices")
            print(f"  {n_txs} ricarica_transactions")
            print(f"  Total: EUR {total_cents/100:,.2f}")

            print("\n=== Validation ===")
            r = await conn.execute(
                text("""
                    SELECT b.name, count(d.id) AS n
                    FROM bars b
                    LEFT JOIN bar_devices d
                      ON d.bar_id = b.id AND d.event_id = b.event_id
                    WHERE b.tenant_id = CAST(:t AS uuid)
                      AND b.event_id  = CAST(:e AS uuid)
                    GROUP BY b.name ORDER BY b.name
                """),
                {"t": tenant_id, "e": event_id},
            )
            for row in r:
                print(f"  bar_devices for {row.name:20} = {row.n}")

            r = await conn.execute(
                text("""
                    SELECT count(*) AS n,
                           COALESCE(sum(amount_cents), 0) / 100.0 AS total_eur
                    FROM ricarica_transactions
                    WHERE event_id = CAST(:e AS uuid)
                      AND source = 'slesh_export'
                """),
                {"e": event_id},
            )
            rv = r.first()
            print(f"  ricarica_transactions: {rv.n} rows, total EUR {rv.total_eur:,.2f}")

            if dry_run:
                print("\n=== DRY RUN: rolling back ===")
                await trans.rollback()
            else:
                print("\n=== Committing ===")
                await trans.commit()
        except Exception:
            print("\n=== ERROR: rolling back ===")
            await trans.rollback()
            raise

    print("\nDone.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--event-id",  required=True)
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--fatturato", type=Path, required=True)
    p.add_argument("--ricariche", type=Path, required=True)
    p.add_argument("--dry-run",   action="store_true")
    args = p.parse_args()
    asyncio.run(run(
        event_id=args.event_id,
        tenant_id=args.tenant_id,
        fatturato_path=args.fatturato,
        ricariche_path=args.ricariche,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
