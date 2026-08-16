#!/usr/bin/env python3
"""smoke_test_july5_transactions.py — insert 10 fake sales into the
LIVE "Sundance July 5 — TEST" event via StockTransactionService.ingest_sale
(NOT a raw INSERT) so the depletion cascade actually runs.

THROWAWAY TEST UTILITY. LOCAL DATABASE ONLY — asserts 'localhost' is in
DATABASE_URL before touching anything.

Event ID:  4fe75619-2f67-4543-95c9-c86e89fc6d70 (Sundance July 5 — TEST, LIVE)
Tenant ID: 25ef916c-a288-44ae-b17c-8dfd09390834 (Noma)
Bar Main:  b85f5867-465e-4989-89f2-53d269944370

Idempotent: source_idempotency_key = f'smoke-july5-{i}' — re-running
this script is a no-op replay per transaction, not a duplicate insert
(StockTransactionService checks the key before doing any other work).

─── READ BEFORE RUNNING: the depletion cascade will NOT fire ──────────
Verified via psql before writing this script:
  - Zero recipe_items link SPRITZ/GIN TONIC/HEINEKEN/PROSECCO to
    Aperol/Beefeater/Serena Prosecco/anything — only 2 recipes exist
    for this ENTIRE tenant, and neither is for these 4 drinks.
  - Zero bar_stock rows exist at Bar Main for this event for ANY of
    the 4 drinks OR their expected ingredients.
ingest_sale handles both gracefully (no exception) rather than
crashing: plan_parent_decrement() treats a missing bar_stock row as a
100% deficit sale (see cascade.py), and a missing recipe means
ingredient_plans stays empty — zero child transactions, ever, for
these products as currently configured. So this script WILL prove
ingest_sale + idempotency + revenue accounting work end-to-end, but it
CANNOT demonstrate cascade depletion (no children will be created, and
Aperol/Beefeater/Heineken-keg/Serena Prosecco bar_stock will not move)
until recipes + bar_stock allocations exist for this event. That's a
menu/allocation-data gap, not a bug in this script — deliberately not
"fixed" here since creating recipes/allocations is a different,
bigger action than "insert 10 fake sales." Flagged in the report.

Usage:
    venv/bin/python scripts/smoke_test_july5_transactions.py
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.auth.models import User  # noqa: F401 (needed for ORM mapper init — see app/workers/tasks.py)
from app.modules.products.models import Product, ProductType
from app.modules.stock_transactions.models import PaymentType, TransactionSource
from app.modules.stock_transactions.schemas import SaleIngestRequest
from app.modules.stock_transactions.service import StockTransactionService

TENANT_ID = UUID("25ef916c-a288-44ae-b17c-8dfd09390834")
EVENT_ID = UUID("4fe75619-2f67-4543-95c9-c86e89fc6d70")
BAR_ID = UUID("b85f5867-465e-4989-89f2-53d269944370")

# (product name, qty, price EUR) — prices as given in the task brief.
# NOTE: the event's actual configured menu prices (event_products) are
# different — SPRITZ=€10, GIN TONIC=€12, HEINEKEN=€7, PROSECCO=€7 — but
# ingest_sale takes an explicit price_cents per sale (it doesn't derive
# it from the menu), and the task's own expected-revenue check (€63)
# is built on these numbers, so they're used as given rather than
# silently swapped for the real menu price. Flagged in the report.
DRINK_ORDERS: list[tuple[str, int, int]] = [
    ("SPRITZ", 3, 6),
    ("GIN TONIC", 2, 8),
    ("HEINEKEN", 3, 5),
    ("PROSECCO", 2, 7),
]

SLEEP_SECONDS = 3


def _assert_local_db() -> None:
    url = settings.database_url
    if "localhost" not in url and "127.0.0.1" not in url:
        raise RuntimeError(
            f"Refusing to run: DATABASE_URL does not look like localhost: {url}"
        )


async def _lookup_product_id(db, name: str) -> UUID:
    stmt = (
        select(Product.id)
        .where(Product.tenant_id == TENANT_ID)
        .where(Product.product_type == ProductType.DRINK)
        .where(Product.name == name)
    )
    product_id = (await db.execute(stmt)).scalar_one_or_none()
    if product_id is None:
        raise RuntimeError(f"No drink product named {name!r} found for tenant {TENANT_ID}")
    return product_id


async def main() -> int:
    _assert_local_db()
    print(f"DATABASE_URL confirmed local: {settings.database_url}\n")

    async with AsyncSessionLocal() as db:
        product_ids: dict[str, UUID] = {}
        for name, _, _ in DRINK_ORDERS:
            product_ids[name] = await _lookup_product_id(db, name)
    print("Resolved product_ids:")
    for name, pid in product_ids.items():
        print(f"  {name}: {pid}")

    # Flatten the order list into 10 individual one-drink sales, in order.
    sales: list[tuple[str, int]] = []
    for name, qty, price_eur in DRINK_ORDERS:
        sales.extend([(name, price_eur)] * qty)

    print(f"\nInserting {len(sales)} sales via ingest_sale, {SLEEP_SECONDS}s apart...\n")

    succeeded = 0
    for i, (name, price_eur) in enumerate(sales):
        async with AsyncSessionLocal() as db:
            service = StockTransactionService(db)
            data = SaleIngestRequest(
                event_id=EVENT_ID,
                bar_id=BAR_ID,
                product_id=product_ids[name],
                qty=Decimal("1"),
                price_cents=price_eur * 100,
                source=TransactionSource.SLESH_POS,
                payment_type=PaymentType.CARD,
                source_idempotency_key=f"smoke-july5-{i}",
            )
            try:
                result = await service.ingest_sale(TENANT_ID, data)
                await db.commit()
                replay_note = " (idempotent replay)" if result.idempotency_replay else ""
                print(
                    f"[{i}] {name} €{price_eur} -> tx={result.parent.id} "
                    f"deficit_qty={result.parent.deficit_qty} "
                    f"children={len(result.children)}{replay_note}"
                )
                succeeded += 1
            except Exception as e:  # noqa: BLE001 — smoke test: log and continue
                await db.rollback()
                print(f"[{i}] {name} €{price_eur} -> ERROR: {e}")

        if i < len(sales) - 1:
            await asyncio.sleep(SLEEP_SECONDS)

    print(f"\n{succeeded}/{len(sales)} transactions succeeded.")
    return 0 if succeeded == len(sales) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
