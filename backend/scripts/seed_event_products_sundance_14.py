#!/usr/bin/env python3
"""Seed event_products for an active Sundance 14 prod event.

Links the 15 catalog drinks × 3 drink bars + 10 food items × matching
food trucks into event_products. Without this, /events/{id}/edit shows
"Listini: add at least one product" because the editor reads from
event_products (per-event menu), not from the global products catalog
that setup_sundance_14_prod.py populates.

Idempotent: skips (event, bar, product) tuples that already exist.

Usage (Railway Console after deploy):
    python scripts/seed_event_products_sundance_14.py
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Model registry warmup (same pattern as setup_sundance_14_prod.py)
from app.modules.auth.models import Tenant, User  # noqa: F401
from app.modules.venues.models import Venue  # noqa: F401
from app.modules.events.models import Event, EventStatus
from app.modules.bars.models import Bar
from app.modules.products.models import Product, ProductType
from app.modules.event_products.models import EventProduct
from app.core.database import AsyncSessionLocal
from scripts.simulate_sundance_14 import (
    NOMA_TENANT_ID, DRINK_MENU, FOOD_MENU,
)

EVENT_NAME = "Sundance 14"


async def main() -> None:
    async with AsyncSessionLocal() as session:
        q = await session.execute(
            select(Event)
            .where(
                Event.tenant_id == NOMA_TENANT_ID,
                Event.name == EVENT_NAME,
                Event.status.notin_([EventStatus.COMPLETED, EventStatus.CANCELLED]),
            )
            .order_by(Event.created_at.desc())
        )
        event = q.scalars().first()
        if event is None:
            print(f"⚠ No active '{EVENT_NAME}' event found.")
            return
        print(f"✓ Event: {event.id} ({event.status.name})")

        bq = await session.execute(select(Bar).where(Bar.event_id == event.id))
        bars = bq.scalars().all()
        drink_bars = [b for b in bars if b.bar_type == "drinks"]
        food_bars = {b.name: b for b in bars if b.bar_type == "food"}
        print(f"✓ {len(drink_bars)} drink bars, {len(food_bars)} food bars")

        pq = await session.execute(
            select(Product).where(Product.tenant_id == NOMA_TENANT_ID)
        )
        catalog = {(p.name, p.product_type): p for p in pq.scalars().all()}

        eq = await session.execute(
            select(EventProduct).where(EventProduct.event_id == event.id)
        )
        existing = {(ep.bar_id, ep.product_id) for ep in eq.scalars().all()}

        created = 0
        skipped = 0
        missing = []

        # Drinks → all 3 drink bars (per Excel: shared "Cocktail Bar" menu)
        for name, price_cents, _cat, _unit, _w in DRINK_MENU:
            product = catalog.get((name, ProductType.DRINK))
            if not product:
                missing.append(f"drink:{name}")
                continue
            for bar in drink_bars:
                if (bar.id, product.id) in existing:
                    skipped += 1
                    continue
                session.add(EventProduct(
                    tenant_id=NOMA_TENANT_ID,
                    event_id=event.id,
                    bar_id=bar.id,
                    product_id=product.id,
                    price_cents=price_cents,
                    is_available=True,
                ))
                created += 1

        # Food → matching truck only
        for bar_name, items in FOOD_MENU.items():
            bar = food_bars.get(bar_name)
            if not bar:
                missing.append(f"food_bar:{bar_name}")
                continue
            for name, price_cents, _w, _ftype in items:
                product = catalog.get((name, ProductType.FOOD))
                if not product:
                    missing.append(f"food:{name}")
                    continue
                if (bar.id, product.id) in existing:
                    skipped += 1
                    continue
                session.add(EventProduct(
                    tenant_id=NOMA_TENANT_ID,
                    event_id=event.id,
                    bar_id=bar.id,
                    product_id=product.id,
                    price_cents=price_cents,
                    is_available=True,
                ))
                created += 1

        await session.commit()
        print(f"✅ Created {created} event_products, skipped {skipped} existing")
        if missing:
            print(f"⚠ Missing: {missing}")


if __name__ == "__main__":
    asyncio.run(main())
