"""CLI: find Slesh products that never matched our catalog for an event.

Usage:
    python -m app.scripts.find_unmapped_products \\
        --tenant-id 25ef916c-a288-44ae-b17c-8dfd09390834 \\
        --event-id 0888f4b7-7030-426b-815c-938e6ca447a6

WHY THIS EXISTS
----------------
order_ingester._ingest_line skips a cart line entirely — no
stock_transactions row, no warning surfaced anywhere durable — when
line.product (Slesh's external product id) has no matching
products.external_pos_id in our catalog. That line's revenue is still
recorded at the order level (event_orders.fiscal_gross_cents), but its
drink/food detail is gone forever; it can never be recovered from our
own database because we never stored it.

Our DB has no record of what these products WERE (no name, no id we
recognize) — the only place that information still exists is Slesh
itself, via CartLine._productName on the raw order. This script re-pulls
an event's orders (same proven-safe 5-minute chunking as
backfill_customer_identity.py — Slesh pages at 100 documents and
silently truncates past that within one window) and reports every
distinct unmapped product by name, with the number of DISTINCT ORDERS
it appears in.

Read-only against both Slesh and Postgres. Never writes anything —
fixing the catalog (adding the missing external_pos_id mappings) is a
separate, deliberate action once you've reviewed this list.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.auth.models import Tenant
from app.modules.events.models import Event, EventOrder
from app.modules.pos.adapters.slesh import SleshAdapter
from app.modules.products.models import Product

logger = logging.getLogger(__name__)


class _TruncationWatchdog(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if "chunk truncated" in msg or "pagination loop detected" in msg:
            self.messages.append(msg)


def _display_name(product_name) -> str:
    """CartLine.product_name is dict[str,str] | str | None (Slesh sends a
    localized-name object sometimes). Pick a readable string."""
    if product_name is None:
        return "(no name from Slesh)"
    if isinstance(product_name, str):
        return product_name
    if isinstance(product_name, dict):
        for key in ("it", "en"):
            if key in product_name and product_name[key]:
                return product_name[key]
        return next(iter(product_name.values()), "(unnamed)")
    return str(product_name)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="find_unmapped_products")
    tenant = p.add_mutually_exclusive_group(required=True)
    tenant.add_argument("--tenant-slug")
    tenant.add_argument("--tenant-id")
    p.add_argument("--event-id", required=True)
    p.add_argument("--chunk-minutes", type=int, default=5)
    p.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


async def _resolve_tenant_id(db, *, slug: str | None, tenant_id: str | None) -> UUID:
    if tenant_id:
        res = await db.execute(select(Tenant).where(Tenant.id == UUID(tenant_id)))
    else:
        res = await db.execute(select(Tenant).where(Tenant.slug == slug))
    t = res.scalar_one_or_none()
    if t is None:
        raise SystemExit(f"❌ Tenant {tenant_id or slug!r} not found.")
    return t.id


async def _run(args) -> int:
    logging.basicConfig(level=args.log_level, format="%(asctime)s | %(levelname)-7s | %(message)s")
    if not settings.slesh_api_token or not settings.slesh_brand_id:
        print("❌ SLESH_API_TOKEN / SLESH_BRAND_ID not configured")
        return 1

    event_id = UUID(args.event_id)

    async with AsyncSessionLocal() as db:
        tenant_id = await _resolve_tenant_id(db, slug=args.tenant_slug, tenant_id=args.tenant_id)
        event = await db.get(Event, event_id)
        if event is None:
            raise SystemExit(f"❌ Event {event_id} not found.")

        res = await db.execute(
            select(EventOrder.created_at_slesh).where(
                EventOrder.tenant_id == tenant_id, EventOrder.event_id == event_id,
            )
        )
        timestamps = [row[0] for row in res.fetchall()]
        if not timestamps:
            raise SystemExit("❌ no event_orders rows for this event — nothing to check.")

        res2 = await db.execute(
            select(Product.external_pos_id).where(
                Product.tenant_id == tenant_id, Product.external_pos_id.is_not(None),
            )
        )
        known_ids = {row[0] for row in res2.fetchall()}

    from_ts = min(timestamps) - timedelta(hours=3)
    to_ts = max(timestamps) + timedelta(hours=3)
    chunk = timedelta(minutes=args.chunk_minutes)

    print(f"event: {event.name} ({event.id})")
    print(f"known external_pos_id count in catalog: {len(known_ids)}")
    print(f"fetch window: [{from_ts.isoformat()} -> {to_ts.isoformat()}]  (chunk={args.chunk_minutes}min)")
    print()

    # (external_pos_id, display_name) -> set of order ids it appeared in
    unmapped_orders: dict[tuple[str, str], set[str]] = {}
    line_count: Counter[tuple[str, str]] = Counter()

    watchdog = _TruncationWatchdog()
    alogger = logging.getLogger("app.modules.pos.adapters.slesh")
    alogger.addHandler(watchdog)
    orders_scanned = 0
    try:
        async with SleshAdapter(token=settings.slesh_api_token, brand_id=settings.slesh_brand_id) as adapter:
            cursor = from_ts
            while cursor < to_ts:
                chunk_until = min(cursor + chunk, to_ts)
                async for order in adapter.list_orders(since_ts=cursor, until_ts=chunk_until, experience_id=None):
                    orders_scanned += 1
                    for line in order.cart:
                        if line.product in known_ids:
                            continue
                        key = (line.product, _display_name(line.product_name))
                        unmapped_orders.setdefault(key, set()).add(order.id)
                        line_count[key] += 1
                cursor = chunk_until
    finally:
        alogger.removeHandler(watchdog)

    print(f"orders scanned: {orders_scanned}")
    print(f"truncation warnings: {len(watchdog.messages)}"
          + ("  <-- INVESTIGATE, list below is unreliable" if watchdog.messages else "  (clean)"))
    print()
    print(f"distinct unmapped products: {len(unmapped_orders)}")
    print(f"{'external_pos_id':26s}  {'orders':>7s}  {'lines':>6s}  name")
    for key, order_ids in sorted(unmapped_orders.items(), key=lambda kv: -len(kv[1])):
        ext_id, name = key
        print(f"{ext_id:26s}  {len(order_ids):7d}  {line_count[key]:6d}  {name}")

    return 0


def main() -> None:
    p = _build_parser()
    sys.exit(asyncio.run(_run(p.parse_args())))


if __name__ == "__main__":
    main()
