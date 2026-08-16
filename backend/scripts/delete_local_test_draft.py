#!/usr/bin/env python3
"""delete_local_test_draft.py — remove the broken "Sundance 15" local
test draft (35bc97f5-7525-46af-8f85-4f7a8459e26d), created against a
generic Sundance 14 DRAFT template with fictional bar names and no
Slesh linkages. Superseded by create_july5_test_draft.py, which builds
a draft matching the REAL production Sundance 14's bar layout.

THROWAWAY TEST UTILITY. LOCAL DATABASE ONLY — refuses to run against
anything but localhost (see the DATABASE_URL assertion below).

Deletes via `DELETE FROM events WHERE id = ...` and relies on FK
CASCADE (verified beforehand: bars, event_products,
event_category_ingredients, event_stock_bar_allocations, bar_stock,
stock_transactions, delivery_invoices, alerts, predictions, reports,
etc. all have event_id FKs with ON DELETE CASCADE).

Usage (from the backend/ directory, so `app` resolves on sys.path):
    PYTHONPATH=. venv/bin/python scripts/delete_local_test_draft.py
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.core.database import engine

BROKEN_DRAFT_ID = "35bc97f5-7525-46af-8f85-4f7a8459e26d"


def _assert_local_db() -> None:
    url = str(engine.url)
    if "localhost" not in url and "127.0.0.1" not in url:
        raise SystemExit(
            f"REFUSING TO RUN: DATABASE_URL does not look local: {url!r}. "
            "This script only ever touches the local dev database."
        )


async def main() -> int:
    _assert_local_db()

    async with engine.begin() as conn:
        r = await conn.execute(
            text("SELECT id, name, status FROM events WHERE id = :id"),
            {"id": BROKEN_DRAFT_ID},
        )
        row = r.mappings().first()
        if row is None:
            print(f"SKIP: event {BROKEN_DRAFT_ID} does not exist (already deleted).")
            return 0

        print(f"Deleting event {row['id']} ({row['name']!r}, status={row['status']})...")
        result = await conn.execute(
            text("DELETE FROM events WHERE id = :id"),
            {"id": BROKEN_DRAFT_ID},
        )
        print(f"  {result.rowcount} event row(s) deleted (cascades handle the rest).")

    async with engine.connect() as conn:
        r = await conn.execute(
            text("SELECT COUNT(*) FROM events WHERE id = :id"),
            {"id": BROKEN_DRAFT_ID},
        )
        count = r.scalar()
        for table in ("bars", "event_products", "event_category_ingredients", "event_stock_bar_allocations"):
            rr = await conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE event_id = :id"),
                {"id": BROKEN_DRAFT_ID},
            )
            print(f"  {table}: {rr.scalar()} rows remaining")

    print(f"VERIFY: events WHERE id = '{BROKEN_DRAFT_ID}' -> {count} rows")
    return 0 if count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
