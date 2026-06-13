#!/usr/bin/env python3
"""Sundance 14 PRODUCTION event setup — pre-stages everything so Hesam
or Omar only needs to press 'Go Live' tomorrow.

Creates:
    - Sundance 14 event (DRAFT status, scheduled for June 14 evening)
    - 7 bars (3 drink + 3 food + 1 service) with device counts from Excel
    - 15 drink products + 10 food products in Noma catalog
    - 31 EventStockItem rows from Partesa invoice 5812120214
    - GIN No 3 sponsor (60 bottles → NO.3 BAR)
    - Baseline dispatches (40% of stock to drink bars by device weight)
    - 24 EventCategoryIngredient rules (Slesh category → bottle depletion)

Food revenue share: 30% Omar / 70% trucks (real partnership terms).

Tomorrow workflow:
    1. Open /events → find "Sundance 14" → press Go Live
    2. Slesh devices ring orders → bars sync → KPIs flow → alerts fire
    3. Bartenders rotate stock via /inventory page

Usage:
    cd backend && source venv/bin/activate
    python scripts/setup_sundance_14_prod.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force model registry (same pattern as simulator)
from app.modules.auth.models import Tenant, User  # noqa: F401
from app.modules.venues.models import Venue
from app.modules.events.models import Event, EventStatus
from app.modules.bars.models import Bar
from app.modules.products.models import (  # noqa: F401
    FoodType, Product, ProductCategory, ProductType, ProductUnit,
)
from app.modules.event_products.models import EventProduct  # noqa: F401
from app.modules.bar_stock.models import BarStock  # noqa: F401
from app.modules.recipes.models import Recipe, RecipeItem  # noqa: F401
from app.modules.stock_transactions.models import (  # noqa: F401
    StockTransaction, TransactionSource, PaymentType,
)
from app.modules.chat.models import (  # noqa: F401
    ChatAttachment, Channel, ChannelMember, ChatMention, ChatMessage,
)
from app.modules.event_storage.models import (
    SupplierProduct as SP,
    EventStockItem as ESI,
    EventStockBarAllocation as ESBA,
)
from app.modules.event_storage.recipe_seeder import (
    ensure_gin_no_3_for_no3_bar,
    seed_recipe_for_event,
)
from app.modules.event_storage.sundance_14_recipe import SUNDANCE_14_RECIPE
from app.core.database import AsyncSessionLocal
from sqlalchemy import select

# Reuse simulator constants — single source of truth for bar config,
# menus, and Partesa quantities. ONLY override event name + share.
from scripts.simulate_sundance_14 import (
    NOMA_TENANT_ID, OMAR_USER_ID,
    BARS, DRINK_MENU, FOOD_MENU, PARTESA_INVOICE_QTY,
    BASELINE_DISPATCH_FRACTION,
    _find_or_create_venue, _find_or_create_product,
    _bars_for_event, _declare_storage_and_dispatch,
)

EVENT_NAME = "Sundance 14"  # NO simulation suffix
FOOD_REVENUE_SHARE_PCT = 30  # Updated per Omar — 30% Omar, 70% trucks


async def main() -> None:
    async with AsyncSessionLocal() as session:
        # 0. Refuse to double-stage
        existing_q = await session.execute(
            select(Event)
            .where(
                Event.tenant_id == NOMA_TENANT_ID,
                Event.name == EVENT_NAME,
                Event.status.notin_([EventStatus.COMPLETED, EventStatus.CANCELLED]),
            )
            .order_by(Event.created_at.desc())
        )
        existing = existing_q.scalars().first()
        if existing:
            print(f"⚠️  '{EVENT_NAME}' already exists: {existing.id} ({existing.status.name})")
            print(f"   To re-stage, mark COMPLETED via SQL then re-run.")
            return

        # 1. Venue
        venue = await _find_or_create_venue(session)

        # 2. Event in DRAFT — scheduled for Sundance 14 evening Rome time.
        # Rome is UTC+2 in June (CEST). Hard-coded to June 14, 2026 19:00 Rome
        # = 17:00 UTC. The auto-transition cron triggers Go Live when status is
        # SCHEDULED + scheduled_at <= now. We keep status=DRAFT and a future
        # scheduled_at so nothing flips until Omar/Hesam press Go Live manually
        # from the /events page.
        scheduled_at = datetime(2026, 6, 14, 17, 0, 0, tzinfo=timezone.utc)
        scheduled_end_at = datetime(2026, 6, 15, 3, 0, 0, tzinfo=timezone.utc)
        event = Event(
            tenant_id=NOMA_TENANT_ID,
            venue_id=venue.id,
            name=EVENT_NAME,
            status=EventStatus.DRAFT,
            scheduled_at=scheduled_at,
            scheduled_end_at=scheduled_end_at,
            expected_guest_count=1600,
            food_revenue_share_pct=FOOD_REVENUE_SHARE_PCT,
        )
        session.add(event)
        await session.flush()
        print(f"✓ Event: '{EVENT_NAME}' DRAFT @ {scheduled_at.isoformat()} ({event.id})")

        # 3. Bars
        for name, bar_type, devices in BARS:
            session.add(Bar(
                tenant_id=NOMA_TENANT_ID,
                event_id=event.id,
                name=name,
                bar_type=bar_type,
                device_count=devices,
                is_active=True,
                auto_created=False,
            ))
        await session.flush()
        print(f"✓ {len(BARS)} bars")

        # 4. Catalog products (idempotent — find-or-create)
        for name, price, cat, unit, _w in DRINK_MENU:
            await _find_or_create_product(
                session, name, ProductType.DRINK, cat, unit, price,
            )
        print(f"✓ {len(DRINK_MENU)} drink products")
        n_food = 0
        for items in FOOD_MENU.values():
            for name, price, _w, food_type in items:
                await _find_or_create_product(
                    session, name, ProductType.FOOD, None,
                    ProductUnit.PIECE, price, food_type=food_type,
                )
                n_food += 1
        print(f"✓ {n_food} food products")

        # 5. Storage + baseline dispatches
        drink_bars = [
            b for b in await _bars_for_event(session, event.id)
            if b.bar_type == "drinks"
        ]
        n_items, n_dispatches = await _declare_storage_and_dispatch(
            session, event.id, drink_bars,
        )
        print(f"✓ {n_items} storage items + {n_dispatches} baseline dispatches")

        # 6. GIN No 3 sponsor (60 bottles → NO.3 BAR)
        await ensure_gin_no_3_for_no3_bar(
            session=session, tenant_id=NOMA_TENANT_ID, event_id=event.id,
        )
        print(f"✓ GIN No 3 (60 bottles) → NO.3 BAR")

        # 7. Recipe rules
        rcounts = await seed_recipe_for_event(
            session=session, tenant_id=NOMA_TENANT_ID, event_id=event.id,
            recipe=SUNDANCE_14_RECIPE,
        )
        print(
            f"✓ Recipe: {rcounts['created']} rules created, "
            f"{rcounts['skipped']} pre-existing, "
            f"{len(rcounts['unresolved_products'])} unresolved"
        )
        for cat, name in rcounts['unresolved_products']:
            print(f"  ⚠️  {cat} → '{name}' (recipe rule skipped)")

        await session.commit()

    print()
    print("=" * 60)
    print(f"✅ Sundance 14 STAGED — ready for kickoff.")
    print(f"   Status: DRAFT")
    print(f"   Food share: Omar {FOOD_REVENUE_SHARE_PCT}% / trucks {100 - FOOD_REVENUE_SHARE_PCT}%")
    print(f"   Tomorrow: open /events → press Go Live.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
