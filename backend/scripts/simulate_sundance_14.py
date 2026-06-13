#!/usr/bin/env python3
"""Sundance 14 end-to-end simulator.

Uses Omar's real Excel data (bars, menu, pricing) to spin up a LIVE
event in Noma tenant and inject synthetic Slesh-shaped orders at a
realistic 10-minute compressed curve (arrival -> steady -> peak ->
wind down). Designed to stress-test the dashboard, polling pipe, and
inventory flow before June 14 with real data shapes.

Subcommands:
    setup       create event + bars + menu products (idempotent)
    go-live     promote sim event DRAFT -> LIVE
    run         generate orders for N seconds (default 600 = 10 min)
    cleanup     mark sim event COMPLETED; keep catalog for real event

Usage:
    cd backend && source venv/bin/activate
    python scripts/simulate_sundance_14.py setup
    python scripts/simulate_sundance_14.py go-live
    python scripts/simulate_sundance_14.py run --duration 600
    python scripts/simulate_sundance_14.py cleanup

While `run` is happening, watch /dashboard /inventory /warehouse in
Chrome. Dispatch some Beefeater to MAIN BAR via the Inventory modal
mid-run to verify cross-page sync.

Skips RESP. BAR per project decision (device count not in Excel).
Skips alerts / burn-rate validation per project scope (recipe gap).
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

# Make `app.*` imports resolvable when running this script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Force full model registry — mirrors alembic/env.py exactly. Without
# all FK targets registered, SQLAlchemy can't resolve FKs at flush time
# (e.g. stock_transactions.bar_stock_id -> bar_stock.id).
from app.modules.auth.models import Tenant, User  # noqa: F401
from app.modules.venues.models import Venue  # noqa: F401
from app.modules.events.models import Event, EventStatus  # noqa: F401
from app.modules.bars.models import Bar  # noqa: F401
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
from app.modules.event_storage.models import (  # noqa: F401
    SupplierProduct, EventStockItem, EventStockBarAllocation,
)
from app.modules.event_storage.recipe_seeder import (
    ensure_gin_no_3_for_no3_bar,
    seed_recipe_for_event,
)
from app.modules.event_storage.sundance_14_recipe import SUNDANCE_14_RECIPE
# (already in registry above — explicit re-import for direct use below)
from app.modules.event_storage.models import (
    SupplierProduct as SP,
    EventStockItem as ESI,
    EventStockBarAllocation as ESBA,
)
from app.core.database import AsyncSessionLocal


NOMA_TENANT_ID = UUID("25ef916c-a288-44ae-b17c-8dfd09390834")
OMAR_USER_ID   = UUID("abef43be-44c5-4041-94a4-09a265d71698")
EVENT_NAME = "Sundance 14 — SIMULATION"

# Omar keeps 20% of food revenue; food trucks keep 80%. Matches the
# real partnership shape described in events.food_revenue_share_pct.
FOOD_REVENUE_SHARE_PCT = 20

# Real Partesa invoice 5812120214 quantities. Maps supplier_products.item_name
# (already seeded into Noma's catalog) to qty_received for the sim event.
# Total: 31 items / €18,431.02 / received 09 June 2026.
PARTESA_INVOICE_QTY: dict[str, int] = {
    "WYBOROWA 1LT VODKA":                          30,
    "ABSOLUT 1LT VODKA":                            6,
    "BEEFEATER LONDON DRY 1LT GIN":               240,
    "GAL41 LIQ.ID LONDON DRY GIN 70 CL":           18,
    "APEROL BARBIERI 1LT":                          8,
    "FOUR ROSES 1LT WHISKEY":                      12,
    "HAVANA CLUB ANEJO 7YO 1LT RUM":               12,
    "OLMECA ALTOS PLATA 70CL TEQUILA":             18,
    "DEL MAGUEY VIDA MEZCAL 70CL":                 12,
    "CAMPARI BITTER 1LT":                          10,
    "BIRRA ICHNUSA NON FILTRATA 20 LT FS":         15,
    "BIRRA HEINEKEN 30 LT FS":                     15,
    "BOMBOLE CO2 LT 6 KG 4":                        5,
    "SARTI ROSA 70 CL":                             6,
    "LIQ.ID VERMOUTH DI TORINO 1 LT":               5,
    "VENTURO APERITIVO 70CL":                       6,
    "LIMONCELLO DI CAPRI 1LT":                      6,
    "CAMPARI SODA 10 CL x100 VP":                   2,
    "SERENA B-SIMPLE CUVEE' BRUT 75CL":            30,
    "SERENA B-SIMPLE PROSECCO DOCG 75CL":           5,
    "BIB COCA COLA ZERO 1,5LT PET":                 3,
    "BIB SCHWEPPES TONICA 1 LT PET":               80,
    "BIB SCHWEPPES LIMONE 1LT PET":                15,
    "BIB SCHWEPPES POMPELMO ROSA 18CL X 24 VP":     8,
    "BIB COCA COLA 1,5LT PET":                      5,
    "SUC DERBY BLUE ARANCIA 100% 1 LT PET":         1,
    "SUC DERBY BLUE ANANAS 100% 1 LTx6 PET":        1,
    "ACQ LEVISSIMA RPET GAS 50CLX24 PET":          10,
    "ACQ LEVISSIMA RPET NAT 50CLX24 PET":          20,
    "ACQ SBENED P.MAIELL.POPOLI GAS 1,5Lx6PET":     6,
    "ACQ SBENED P.MAIELL.POPOLI MGAS1,5Lx6PET":     4,
}

# What fraction of the pool gets pre-dispatched to drink bars at LIVE.
# The remainder stays in the warehouse for Omar to dispatch during the
# event via the Inventory page. 0.4 = 40% baseline, 60% in warehouse.
BASELINE_DISPATCH_FRACTION = 0.4


# ─── Bar config (from Omar's Excel, RESP. BAR skipped) ────────────────

BARS = [
    # (name,         bar_type,  device_count)
    ("MAIN BAR",     "drinks",  9),
    ("NO.3 BAR",     "drinks",  1),
    ("STAGE BAR",    "drinks",  4),
    ("MALANDRINO",   "food",    2),
    ("SCROCCHIA",    "food",    2),
    ("PULLED PORK",  "food",    2),
    ("CASSA",        "service", 4),   # no products sold, top-up only
]


# ─── Drink menu (shared by all 3 drink bars per Excel listino) ────────
#                                                          popularity
DRINK_MENU = [
    # (name, price_cents, ProductCategory, ProductUnit, popularity_weight)
    ("GIN TONIC",                  1200, ProductCategory.BASIC_COCKTAIL,   ProductUnit.GLASS,       15),
    ("DRINK",                      1200, ProductCategory.BASIC_COCKTAIL,   ProductUnit.GLASS,       12),
    ("SPRITZ",                     1000, ProductCategory.BASIC_COCKTAIL,   ProductUnit.GLASS,       20),
    ("SIGNATURE",                  1200, ProductCategory.PREMIUM_COCKTAIL, ProductUnit.GLASS,        5),
    ("PREMIUM",                    1300, ProductCategory.PREMIUM_COCKTAIL, ProductUnit.GLASS,        3),
    ("HEINEKEN",                    700, ProductCategory.BEER_DRAFT,       ProductUnit.DRAFT_GLASS, 15),
    ("ICHNUSA NON FILT.",           800, ProductCategory.BEER_DRAFT,       ProductUnit.DRAFT_GLASS,  8),
    ("PROSECCO",                    700, ProductCategory.WINE_SPARKLING,   ProductUnit.GLASS,        5),
    ("VINO",                        700, ProductCategory.WINE_RED,         ProductUnit.GLASS,        4),
    ("BOTTIGLIA VINO",             2800, ProductCategory.WINE_RED,         ProductUnit.BOTTLE,       1),
    ("BOTTIGLIA PROSECCO",         2800, ProductCategory.WINE_SPARKLING,   ProductUnit.BOTTLE,       1),
    ("BOTTIGLIA METODO CLASSICO",  3600, ProductCategory.WINE_SPARKLING,   ProductUnit.BOTTLE,       1),
    ("SOFT DRINK",                  600, ProductCategory.SOFT_DRINK,       ProductUnit.GLASS,        5),
    ("DRINK ANALCOLICI",            800, ProductCategory.SOFT_DRINK,       ProductUnit.GLASS,        2),
    ("ACQUA",                       200, ProductCategory.SOFT_DRINK,       ProductUnit.BOTTLE,       3),
]


# ─── Food menus (per truck) ───────────────────────────────────────────

FOOD_MENU = {
    "MALANDRINO":  [
        ("Hamburger",     1200, 8, FoodType.BURGERS),
        ("Cheeseburger",  1200, 6, FoodType.BURGERS),
        ("Veggie Burger", 1200, 2, FoodType.BURGERS),
        ("Patatina S",     500, 4, FoodType.FRIED),
        ("Patatina L",     800, 3, FoodType.FRIED),
    ],
    "SCROCCHIA": [
        ("CLASSICA",       700, 5, FoodType.SANDWICHES),
        ("SAPORITA",       800, 4, FoodType.SANDWICHES),
    ],
    "PULLED PORK": [
        ("Pulled",        1200, 5, FoodType.SANDWICHES),
        ("Veggie",        1200, 2, FoodType.SANDWICHES),
        ("Fritto",         800, 3, FoodType.FRIED),
    ],
}


# ─── Helpers ──────────────────────────────────────────────────────────


async def _find_or_create_venue(session: AsyncSession) -> Venue:
    """Find existing Villa Alberico venue or create one."""
    q = await session.execute(
        select(Venue).where(
            Venue.tenant_id == NOMA_TENANT_ID,
            Venue.name == "Villa Alberico",
        )
    )
    venue = q.scalars().first()
    if venue:
        return venue
    venue = Venue(
        tenant_id=NOMA_TENANT_ID,
        name="Villa Alberico",
        address="Via di Fioranello 18, 00178 Roma",
        capacity=1600,
    )
    session.add(venue)
    await session.flush()
    print(f"  + Created venue: Villa Alberico ({venue.id})")
    return venue


async def _find_sim_event(session: AsyncSession) -> Event | None:
    """Find the current ACTIVE sim event. COMPLETED/CANCELLED events
    from prior runs are intentionally excluded so re-running `setup`
    after `cleanup` works without manual SQL surgery. Order by created
    desc so we always get the most recent active one."""
    q = await session.execute(
        select(Event)
        .where(
            Event.tenant_id == NOMA_TENANT_ID,
            Event.name == EVENT_NAME,
            Event.status.notin_([EventStatus.COMPLETED, EventStatus.CANCELLED]),
        )
        .order_by(Event.created_at.desc())
    )
    return q.scalars().first()


async def _find_or_create_product(
    session: AsyncSession,
    name: str,
    product_type: ProductType,
    category: ProductCategory | None,
    unit: ProductUnit,
    price_cents: int | None,
    food_type: FoodType | None = None,
) -> Product:
    """Idempotent product creation. Matches Slesh's reality where the
    same product name might be sold across multiple events."""
    q = await session.execute(
        select(Product).where(
            Product.tenant_id == NOMA_TENANT_ID,
            Product.name == name,
            Product.product_type == product_type,
            Product.is_archived == False,
        )
    )
    p = q.scalars().first()
    if p:
        return p
    p = Product(
        tenant_id=NOMA_TENANT_ID,
        name=name,
        product_type=product_type,
        category=category,
        food_type=food_type,
        unit=unit,
        default_price_cents=price_cents,
        is_archived=False,
    )
    session.add(p)
    await session.flush()
    return p


async def _bars_for_event(session: AsyncSession, event_id: UUID) -> list[Bar]:
    q = await session.execute(
        select(Bar).where(Bar.event_id == event_id, Bar.is_active == True)
    )
    return list(q.scalars().all())


async def _declare_storage_and_dispatch(
    session: AsyncSession,
    event_id: UUID,
    drink_bars: list[Bar],
) -> tuple[int, int]:
    """Create EventStockItem rows from Partesa catalog, then dispatch a
    baseline fraction to drink bars weighted by device_count.

    Returns (n_storage_items, n_dispatches).
    Food bars are explicitly excluded (third-party trucks own their stock).
    """
    # Pull all Noma supplier_products
    q = await session.execute(
        select(SP).where(SP.tenant_id == NOMA_TENANT_ID)
    )
    supplier_products = list(q.scalars().all())

    total_drink_devices = sum(b.device_count for b in drink_bars)
    n_items = 0
    n_dispatches = 0

    for sp in supplier_products:
        qty = PARTESA_INVOICE_QTY.get(sp.item_name)
        if qty is None:
            # Unknown item — declare with qty=1 as a sane fallback so
            # nothing in the catalog is silently dropped.
            qty = 1

        # 1. Storage declaration (the pool)
        # line_total_eur = qty * last_unit_price_eur if we have a price. Without
        # this the Warehouse 'Total Value' KPI falls back to '—' because the
        # backend treats line_total_eur=NULL across all rows as 'no pricing data'.
        line_total = (
            Decimal(qty) * sp.last_unit_price_eur
            if sp.last_unit_price_eur is not None
            else None
        )
        esi = ESI(
            tenant_id=NOMA_TENANT_ID,
            event_id=event_id,
            supplier_product_id=sp.id,
            qty_received=Decimal(qty),
            unit=sp.default_unit,
            line_total_eur=line_total,
        )
        session.add(esi)
        n_items += 1

        # 2. Baseline dispatch to drink bars (40% by device weight)
        baseline_total = int(qty * BASELINE_DISPATCH_FRACTION)
        if baseline_total == 0 or total_drink_devices == 0:
            continue

        for bar in drink_bars:
            share = int(baseline_total * bar.device_count / total_drink_devices)
            if share == 0:
                continue
            esba = ESBA(
                tenant_id=NOMA_TENANT_ID,
                event_id=event_id,
                supplier_product_id=sp.id,
                bar_id=bar.id,
                qty_allocated=Decimal(share),
                dispatched_by_user_id=OMAR_USER_ID,
                notes="Baseline dispatch (simulator setup)",
            )
            session.add(esba)
            n_dispatches += 1

    await session.flush()
    return n_items, n_dispatches


# ─── Subcommands ──────────────────────────────────────────────────────


async def cmd_setup() -> None:
    """Create venue + event + bars + menu products. Idempotent."""
    async with AsyncSessionLocal() as session:
        # Bail if a sim event already exists
        existing = await _find_sim_event(session)
        if existing:
            print(f"⚠ Sim event already exists: {existing.id} ({existing.status.name})")
            print(f"  Run 'cleanup' first if you want to start over.")
            return

        venue = await _find_or_create_venue(session)

        now = datetime.now(timezone.utc)
        event = Event(
            tenant_id=NOMA_TENANT_ID,
            venue_id=venue.id,
            name=EVENT_NAME,
            status=EventStatus.DRAFT,
            # Schedule far enough in future that the auto-transition cron
            # doesn't accidentally promote it on its own — we want to
            # control go-live manually.
            scheduled_at=now + timedelta(hours=2),
            scheduled_end_at=now + timedelta(hours=12),
            expected_guest_count=1600,
            food_revenue_share_pct=FOOD_REVENUE_SHARE_PCT,
        )
        session.add(event)
        await session.flush()
        print(f"✓ Created event: {EVENT_NAME} (DRAFT, {event.id})")

        # Bars
        for name, bar_type, devices in BARS:
            bar = Bar(
                tenant_id=NOMA_TENANT_ID,
                event_id=event.id,
                name=name,
                bar_type=bar_type,
                device_count=devices,
                is_active=True,
                auto_created=False,
            )
            session.add(bar)
        await session.flush()
        print(f"✓ Created {len(BARS)} bars")

        # Drink products (shared catalog, find-or-create)
        for name, price, cat, unit, _w in DRINK_MENU:
            await _find_or_create_product(
                session, name, ProductType.DRINK, cat, unit, price,
            )
        print(f"✓ {len(DRINK_MENU)} drink products in catalog")

        # Food products
        n_food = 0
        for items in FOOD_MENU.values():
            for name, price, _w, food_type in items:
                await _find_or_create_product(
                    session, name, ProductType.FOOD, None,
                    ProductUnit.PIECE, price, food_type=food_type,
                )
                n_food += 1
        print(f"✓ {n_food} food products in catalog")

        # Storage declaration: mirror what Omar's wizard would do — turn
        # the Partesa catalog into per-event purchase rows.
        drink_bars = [
            b for b in await _bars_for_event(session, event.id)
            if b.bar_type == "drinks"
        ]
        n_items, n_dispatches = await _declare_storage_and_dispatch(
            session, event.id, drink_bars,
        )
        print(f"✓ Declared {n_items} storage items from Partesa invoice")
        print(f"✓ Pre-dispatched {n_dispatches} baseline allocations to drink bars")

        # GIN No 3 sponsor — direct supply (not on Partesa invoice). 60 bottles
        # dispatched exclusively to NO.3 BAR.
        _, gin3_alloc_id = await ensure_gin_no_3_for_no3_bar(
            session=session, tenant_id=NOMA_TENANT_ID, event_id=event.id,
        )
        print(f"✓ GIN No 3 sponsor dispatched to NO.3 BAR (60 bottles)")

        # Recipe: Slesh-category → ingredient-pool depletion rules.
        rcounts = await seed_recipe_for_event(
            session=session, tenant_id=NOMA_TENANT_ID, event_id=event.id,
            recipe=SUNDANCE_14_RECIPE,
        )
        print(
            f"✓ Recipe seeded: {rcounts['created']} new rules, "
            f"{rcounts['skipped']} pre-existing, "
            f"{len(rcounts['unresolved_products'])} unresolved products"
        )
        if rcounts['unresolved_products']:
            for cat, name in rcounts['unresolved_products']:
                print(f"  ⚠️  unresolved: {cat} → '{name}'")

        await session.commit()
        print(f"\n✅ Setup complete. Next: ./scripts/simulate_sundance_14.py go-live")


async def cmd_go_live() -> None:
    """Flip the sim event DRAFT -> LIVE manually."""
    async with AsyncSessionLocal() as session:
        event = await _find_sim_event(session)
        if event is None:
            print("✗ No sim event found. Run 'setup' first.")
            return
        if event.status == EventStatus.LIVE:
            print(f"⚠ Event already LIVE ({event.id}). Skipping.")
            return
        if event.status not in (EventStatus.DRAFT, EventStatus.ACTIVE):
            print(f"✗ Event is {event.status.name}; can't promote to LIVE.")
            return

        # Check tenant has no other LIVE event
        other_live_q = await session.execute(
            select(Event).where(
                Event.tenant_id == NOMA_TENANT_ID,
                Event.status == EventStatus.LIVE,
                Event.id != event.id,
            )
        )
        other = other_live_q.scalars().first()
        if other:
            print(f"✗ Another LIVE event blocks: {other.name} ({other.id})")
            print(f"  End it first via SQL: UPDATE events SET status='COMPLETED' WHERE id='{other.id}';")
            return

        event.status = EventStatus.LIVE
        event.started_at = datetime.now(timezone.utc)
        await session.commit()
        print(f"✅ Event → LIVE ({event.id})")
        print(f"   Dashboard at /dashboard should now show it.")
        print(f"   Next: ./scripts/simulate_sundance_14.py run")


async def cmd_run(duration_seconds: int) -> None:
    """Generate orders at a realistic 10-min curve."""
    # Phase schedule: (phase_until_seconds, orders_per_minute)
    PHASES = [
        ( 60,  5),   # T+0-1min     arrival
        (180, 12),   # T+1-3min     daytime
        (420, 35),   # T+3-7min     PEAK (stress)
        (duration_seconds + 1, 10),  # remainder  wind down
    ]

    async with AsyncSessionLocal() as session:
        # Load event
        event = await _find_sim_event(session)
        if event is None or event.status != EventStatus.LIVE:
            print("✗ Sim event not LIVE. Run setup + go-live first.")
            return

        # Load bars
        bars_q = await session.execute(
            select(Bar).where(Bar.event_id == event.id, Bar.is_active == True)
        )
        bars = list(bars_q.scalars().all())
        drink_bars = [b for b in bars if b.bar_type == "drinks"]
        food_bars  = [b for b in bars if b.bar_type == "food"]
        drink_weights = [b.device_count for b in drink_bars]

        # Load drink products (build (product, weight) list)
        drink_pool: list[tuple[Product, int]] = []
        for name, _price, _cat, _unit, weight in DRINK_MENU:
            q = await session.execute(
                select(Product).where(
                    Product.tenant_id == NOMA_TENANT_ID,
                    Product.name == name,
                    Product.product_type == ProductType.DRINK,
                )
            )
            p = q.scalars().first()
            if p:
                drink_pool.append((p, weight))

        # Load food products keyed by bar name
        food_pools: dict[str, list[tuple[Product, int]]] = {}
        for bar_name, items in FOOD_MENU.items():
            pool = []
            for name, _price, weight, _food_type in items:
                q = await session.execute(
                    select(Product).where(
                        Product.tenant_id == NOMA_TENANT_ID,
                        Product.name == name,
                        Product.product_type == ProductType.FOOD,
                    )
                )
                p = q.scalars().first()
                if p:
                    pool.append((p, weight))
            food_pools[bar_name] = pool

        if not drink_pool or not drink_bars:
            print("✗ Missing products or drink bars. Setup may be incomplete.")
            return

        print(f"✓ Loaded {len(bars)} bars, {len(drink_pool)} drink products")
        print(f"✓ Running for {duration_seconds}s with realistic curve")
        print(f"  Phases: arrival(5/m) → daytime(12/m) → PEAK(35/m) → wind(10/m)")
        print()

        start = time.monotonic()
        orders_count = 0
        lines_count = 0
        revenue_cents = 0
        errors = 0
        last_progress = 0.0

        while True:
            elapsed = time.monotonic() - start
            if elapsed >= duration_seconds:
                break

            # Current phase rate
            rate = next(
                (r for until, r in PHASES if elapsed < until),
                PHASES[-1][1],
            )
            mean_interval = 60.0 / rate
            # Poisson-ish jitter: uniform between 50%-150% of mean
            sleep_s = mean_interval * random.uniform(0.5, 1.5)

            # Pick bar — 70% drink, 30% food
            if random.random() < 0.7 or not food_bars:
                bar = random.choices(drink_bars, weights=drink_weights)[0]
                pool = drink_pool
            else:
                bar = random.choice(food_bars)
                pool = food_pools.get(bar.name, drink_pool)

            # 1-4 line items per order. Slesh convention: each line is ONE
            # physical item with qty=1 — a customer who orders 2 beers sends
            # 2 cart lines, not 1 line with qty=2. Mirroring that here keeps
            # us aligned with the KPI service's revenue_expr which assumes
            # price_cents is per-unit (multiplied by qty downstream).
            n_lines = random.choices([1, 2, 3, 4], weights=[6, 3, 2, 1])[0]
            order_id = uuid4()
            order_revenue = 0
            picked_products: list[Product] = []
            weights = [w for _p, w in pool]
            for _ in range(n_lines):
                p, _ = random.choices(pool, weights=weights)[0]
                picked_products.append(p)

            try:
                for p in picked_products:
                    unit_price_cents = p.default_price_cents or 0
                    tx = StockTransaction(
                        tenant_id=NOMA_TENANT_ID,
                        event_id=event.id,
                        bar_id=bar.id,
                        product_id=p.id,
                        # Slesh convention: 1 line = 1 item, qty=1, price_cents
                        # is the UNIT price. The KPI service multiplies qty
                        # by price_cents to get revenue — if we stored a line
                        # total here we'd double-count for qty>1.
                        qty=Decimal(1),
                        deficit_qty=Decimal(0),
                        price_cents=unit_price_cents,
                        source=TransactionSource.SLESH_POS,
                        # TOKEN = NFC wristband, what real Slesh always sends.
                        # Required for the Wristband Activity feed to pick it up.
                        payment_type=PaymentType.TOKEN,
                        source_idempotency_key=f"sim:{order_id}:{uuid4().hex[:8]}",
                    )
                    session.add(tx)
                    lines_count += 1
                    order_revenue += unit_price_cents
                await session.commit()
                orders_count += 1
                revenue_cents += order_revenue
            except Exception as e:
                await session.rollback()
                errors += 1
                if errors <= 3:
                    print(f"  ! error: {e}")

            # Progress every ~10s
            if elapsed - last_progress >= 10:
                phase_label = (
                    "arrival" if elapsed < 60 else
                    "daytime" if elapsed < 180 else
                    "PEAK   " if elapsed < 420 else
                    "wind   "
                )
                print(
                    f"  [T+{int(elapsed):>3}s · {phase_label} · "
                    f"{rate:>2}/m] "
                    f"orders={orders_count:>4} lines={lines_count:>4} "
                    f"€{revenue_cents/100:>7.0f} err={errors}"
                )
                last_progress = elapsed

            await asyncio.sleep(sleep_s)

        elapsed = time.monotonic() - start
        print()
        print("=" * 60)
        print(f"✅ Run complete in {elapsed:.0f}s")
        print(f"   Orders:   {orders_count}")
        print(f"   Lines:    {lines_count}")
        print(f"   Revenue:  €{revenue_cents/100:,.2f}")
        print(f"   Errors:   {errors}")
        print("=" * 60)


async def cmd_recharge(bar_name: str, product_substring: str, qty: float) -> None:
    """Dispatch more of a supplier_product to a bar mid-event. Demo flow:

        python3 scripts/simulate_sundance_14.py recharge \
            --bar "MAIN BAR" --product "SARTI ROSA" --qty 4
    """
    from decimal import Decimal as _D
    async with AsyncSessionLocal() as session:
        eq = await session.execute(
            select(Event).where(
                Event.tenant_id == NOMA_TENANT_ID,
                Event.name == "Sundance 14 — SIMULATION",
                Event.status == EventStatus.LIVE,
            )
        )
        event = eq.scalars().first()
        if event is None:
            print("❌ No LIVE sim event. Run setup + go-live first.")
            return
        bq = await session.execute(
            select(Bar).where(
                Bar.tenant_id == NOMA_TENANT_ID,
                Bar.event_id == event.id,
                Bar.name == bar_name,
            )
        )
        bar = bq.scalars().first()
        if bar is None:
            print(f"❌ Bar '{bar_name}' not found in event.")
            return
        spq = await session.execute(
            select(SupplierProduct).where(
                SupplierProduct.tenant_id == NOMA_TENANT_ID,
                SupplierProduct.item_name.ilike(f"%{product_substring}%"),
            )
        )
        candidates = list(spq.scalars().all())
        if not candidates:
            print(f"❌ No supplier_product matches '{product_substring}'")
            return
        if len(candidates) > 1:
            print(f"⚠️  Ambiguous: {len(candidates)} matches; using first.")
            for c in candidates:
                print(f"   - {c.item_name}")
        sp = candidates[0]
        alloc = EventStockBarAllocation(
            tenant_id=NOMA_TENANT_ID,
            event_id=event.id,
            supplier_product_id=sp.id,
            bar_id=bar.id,
            qty_allocated=_D(str(qty)),
            notes=f"Mid-event recharge ({product_substring})",
        )
        session.add(alloc)
        await session.commit()
        print(
            f"✅ Recharged {qty} {sp.default_unit} of {sp.item_name} → {bar_name}"
        )


async def cmd_cleanup() -> None:
    """Mark sim event COMPLETED. Leaves products + bars in DB for the
    real Sundance 14 event creation (Omar can reuse the catalog)."""
    async with AsyncSessionLocal() as session:
        event = await _find_sim_event(session)
        if event is None:
            print("⚠ No sim event found, nothing to clean.")
            return
        if event.status == EventStatus.COMPLETED:
            print(f"⚠ Already COMPLETED: {event.id}")
            return
        event.status = EventStatus.COMPLETED
        event.ended_at = datetime.now(timezone.utc)
        await session.commit()
        print(f"✅ Event {event.id} → COMPLETED")
        print(f"   Catalog products + supplier_products preserved for real event.")


# ─── CLI ──────────────────────────────────────────────────────────────


async def amain() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    sub.add_parser("go-live")
    run_p = sub.add_parser("run")
    run_p.add_argument("--duration", type=int, default=600,
                       help="Seconds to run (default 600 = 10 min)")
    rch_p = sub.add_parser(
        "recharge",
        help="Dispatch more of a supplier_product to a bar mid-run (demo refill).",
    )
    rch_p.add_argument("--bar", required=True, help="Bar name, e.g. 'MAIN BAR'")
    rch_p.add_argument("--product", required=True,
                       help="Substring of supplier_product item_name, e.g. 'SARTI'")
    rch_p.add_argument("--qty", type=float, required=True,
                       help="Quantity in default_unit (BO/KAR/FS)")
    sub.add_parser("cleanup")
    args = parser.parse_args()

    if args.cmd == "setup":
        await cmd_setup()
    elif args.cmd == "go-live":
        await cmd_go_live()
    elif args.cmd == "run":
        await cmd_run(args.duration)
    elif args.cmd == "recharge":
        await cmd_recharge(args.bar, args.product, args.qty)
    elif args.cmd == "cleanup":
        await cmd_cleanup()


if __name__ == "__main__":
    asyncio.run(amain())
