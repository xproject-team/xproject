#!/usr/bin/env python3
"""backfill_event_orders.py — Phase 2 backfill of event_orders.

Populates event_orders for an event whose Slesh orders were ingested
before the event_orders schema existed (Sundance 14, June 14 2026).
Pulls all Slesh orders in the event window (including cash-desk
orders the live poller skipped) and UPSERTs one row per order with
all order-level financial extras (VAT, deposits, fiscal gross/net,
discount, subtotal).

Idempotent — re-running is safe (UPSERT on tenant_id + slesh_order_id).

Usage from backend/ with venv active OR inside Railway xproject-worker:

  python scripts/backfill_event_orders.py \\
      --event-id 6bd035a9-3ab4-4c7f-8f68-c811aef9fa47 \\
      --from-utc 2026-06-14T10:00:00Z \\
      --to-utc   2026-06-14T23:00:00Z

Add --dry-run to inspect without writing.
"""
import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Force SQLAlchemy model registry population
from app.modules.auth.models import Tenant, User  # noqa: F401
from app.modules.venues.models import Venue  # noqa: F401
from app.modules.events.models import Event, EventOrder  # noqa: F401
from app.modules.products.models import Product  # noqa: F401
from app.modules.bars.models import Bar  # noqa: F401
from app.modules.stock_transactions.models import StockTransaction  # noqa: F401


def _r(v):
    """Round optional float → int cents (VAT splits arrive as fractional)."""
    return None if v is None else int(round(v))


def _to_dt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--event-id", required=True)
    p.add_argument("--from-utc", required=True, help="ISO8601 UTC, e.g. 2026-06-14T10:00:00Z")
    p.add_argument("--to-utc",   required=True)
    p.add_argument("--dry-run",  action="store_true")
    args = p.parse_args()

    event_id = UUID(args.event_id)
    start = datetime.fromisoformat(args.from_utc.replace("Z", "+00:00"))
    end   = datetime.fromisoformat(args.to_utc.replace("Z", "+00:00"))

    from app.core.database import AsyncSessionLocal
    from app.core.config import settings
    from app.modules.pos.adapters.slesh import SleshAdapter

    print(f"Event:   {event_id}")
    print(f"Window:  {start.isoformat()} -> {end.isoformat()}")
    print(f"Dry-run: {args.dry_run}\n")

    async with AsyncSessionLocal() as db:
        ev = (await db.execute(
            select(Event).where(Event.id == event_id)
        )).scalar_one_or_none()
        if ev is None:
            print(f"event {event_id} not found", file=sys.stderr)
            sys.exit(1)

        tenant_id = ev.tenant_id
        bars = (await db.execute(
            select(Bar).where(Bar.tenant_id == tenant_id, Bar.event_id == event_id)
        )).scalars().all()
        shop_to_bar = {b.slesh_negozio_id: b.id for b in bars if b.slesh_negozio_id}
        print(f"Tenant:  {tenant_id}")
        print(f"Bars:    {len(shop_to_bar)} mapped Slesh shops\n")

        adapter = SleshAdapter(
            token=settings.slesh_api_token,
            brand_id=settings.slesh_brand_id,
        )

        seen = inserted = 0
        by_type = {}

        async for order in adapter.list_orders(start, end, order_type=None):
            seen += 1
            by_type[order.type] = by_type.get(order.type, 0) + 1

            shop_id = None
            if order.shop is not None:
                shop_id = order.shop.id if hasattr(order.shop, "id") else order.shop
            bar_id = shop_to_bar.get(shop_id) if shop_id else None

            confirmed = sum(1 for ln in order.cart if ln.status != "refunded")
            refunded  = sum(1 for ln in order.cart if ln.status == "refunded")

            values = dict(
                tenant_id=tenant_id,
                event_id=event_id,
                slesh_order_id=order.id,
                slesh_shop_id=shop_id,
                bar_id=bar_id,
                order_type=order.type,
                subtotal_cents=     _r(order.subtotal),
                vat_cents=          _r(order.cart_vat_amount),
                deposit_cents=      _r(order.cart_deposit_amount),
                fiscal_gross_cents= _r(order.cart_fiscal_gross_amount),
                fiscal_net_cents=   _r(order.cart_fiscal_net_amount),
                discount_cents=     _r(order.cart_discount_amount),
                payment_type=order.payment.type if order.payment is not None else None,
                cart_line_count=len(order.cart),
                confirmed_line_count=confirmed,
                refunded_line_count=refunded,
                created_at_slesh=_to_dt(order.created_at),
            )

            if args.dry_run:
                inserted += 1
                if seen <= 3:
                    print(f"  [dry] {order.type}/{order.id[:8]} shop={shop_id} sub={values['subtotal_cents']}c vat={values['vat_cents']}c")
                continue

            stmt = (
                pg_insert(EventOrder)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["tenant_id", "slesh_order_id"],
                    set_={k: v for k, v in values.items()
                          if k not in ("tenant_id", "slesh_order_id", "event_id")},
                )
            )
            await db.execute(stmt)
            inserted += 1

            if inserted % 500 == 0:
                await db.commit()
                print(f"  ... {inserted} orders committed")

        if not args.dry_run:
            await db.commit()

        print(f"\nSeen:     {seen}")
        print(f"Inserted: {inserted}")
        print(f"By type:  {by_type}")

        if not args.dry_run:
            rows = (await db.execute(
                select(EventOrder).where(EventOrder.event_id == event_id)
            )).scalars().all()
            print(f"event_orders rows for this event: {len(rows)}")


if __name__ == "__main__":
    asyncio.run(main())
