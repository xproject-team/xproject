"""Staging data generator — builds a complete, rehearsal-grade dataset.

Usage (inside the STAGING backend container, from /app):

    python -m app.scripts.build_staging_data           # full build
    python -m app.scripts.build_staging_data --fast    # small windows (tests)

PRODUCTION GUARD — the script REFUSES to run unless ALL THREE hold:

    1. os.environ["ENVIRONMENT"] == "staging"   (exact match, no substring)
    2. settings.pos_adapter      == "fake"      (POS_ADAPTER=fake)
    3. settings.slesh_api_token  == ""          (no live POS credential)

  Production fails all three (ENVIRONMENT=production, no POS_ADAPTER,
  token present); a laptop with no ENVIRONMENT set fails (1). There is
  no override flag. Additionally, the wipe only ever deletes the two
  generator-owned tenant slugs — it cannot touch other tenants even in
  staging.

IDEMPOTENT: every run first deletes the generator's two tenants (the
tenants.id FK cascade removes every dependent row — verified: all
tenant-rooted tables cascade, user_roles cascades via users) and then
rebuilds from scratch. One command, same result every time. The
hand-seeded "staging-demo" tenant is never touched.

WHY BOTH ROLE COLUMNS ARE WRITTEN: login via the frontend is two-step —
roles-for-email, then login WITH requested_role — and both steps read
the user_roles table, the documented multi-role source of truth
(auth/repository.py). users.role alone cannot log in through the UI
(the bug hit while hand-seeding staging). This generator writes BOTH.

DATA COVERAGE (each item exists because a real failure lived there):
  - two tenants (cross-tenant isolation must be testable)
  - alpha: events in draft/active/live/completed states; 3+ completed
    with real ingested POS history so the forecast can fit
  - beta: no completed events — the insufficient-history path runs
  - bars of both types; every mapping from the fake adapter's shop
    list; EXACTLY ONE bar deliberately unmapped (parking rehearsal)
  - every product carries an external_pos_id from FAKE_PRODUCTS_RAW so
    ingested orders deplete stock
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select

import app.models_registry  # noqa: F401 — complete the FK graph for standalone runs
from app.core.config import settings

# ─── Identities (also imported by tests) ─────────────────────────────────────
# (email, password, role, tenant_slug). Staging-only credentials — the
# guard above means these can never land in a production database.
# Domain note: RolesForEmailRequest validates EmailStr, which REJECTS
# special-use TLDs (.local, .test, .example) — an account seeded with
# such a domain passes direct /auth/login but 422s on the frontend's
# roles-for-email step. Fictional but standard-TLD domain used instead.
ACCOUNTS: list[tuple[str, str, str, str]] = [
    ("owner@alpha.xproject-staging.it",   "staging-alpha-owner",   "owner",   "staging-alpha"),
    ("manager@alpha.xproject-staging.it", "staging-alpha-manager", "manager", "staging-alpha"),
    ("owner@beta.xproject-staging.it",    "staging-beta-owner",    "owner",   "staging-beta"),
]

TENANTS: list[tuple[str, str]] = [
    ("Staging Alpha", "staging-alpha"),
    ("Staging Beta", "staging-beta"),
]

LOCAL_EVENT_START_HOUR = 18  # completed-event windows open at the fake's ramp


class StagingGuardError(SystemExit):
    """Raised (exits non-zero) when the environment is not provably staging."""


def assert_staging() -> None:
    problems = []
    if os.environ.get("ENVIRONMENT") != "staging":
        problems.append(
            f"ENVIRONMENT={os.environ.get('ENVIRONMENT')!r} (must be exactly 'staging')"
        )
    if (settings.pos_adapter or "").strip().lower() != "fake":
        problems.append(f"POS_ADAPTER={settings.pos_adapter!r} (must be 'fake')")
    if settings.slesh_api_token:
        problems.append("SLESH_API_TOKEN is set (a live POS credential exists here)")
    if problems:
        raise StagingGuardError(
            "REFUSING to generate data — this environment is not provably staging:\n  - "
            + "\n  - ".join(problems)
        )


async def wipe() -> None:
    """Delete the generator's two tenants and every row they own.

    event_orders is deleted EXPLICITLY, first: it is the one
    tenant-scoped table whose migration (eo1) created no foreign keys at
    all — the ORM model declares CASCADE FKs the database does not have
    (model/migration drift, Day-5 finding) — so relying on tenant-FK
    cascade left every prior generation's orders orphaned (28,178
    accumulated on staging over three days of regenerates). Every other
    generator-owned table cascades from the tenant delete (verified
    against information_schema on the real schema).

    Never touches any other tenant. Guarded like build().
    """
    assert_staging()
    from app.core.database import AsyncSessionLocal
    from app.modules.auth.models import Tenant
    from app.modules.events.models import EventOrder

    slugs = [slug for _n, slug in TENANTS]
    async with AsyncSessionLocal() as db:
        tenant_ids = select(Tenant.id).where(Tenant.slug.in_(slugs)).scalar_subquery()
        await db.execute(delete(EventOrder).where(EventOrder.tenant_id.in_(tenant_ids)))
        await db.execute(delete(Tenant).where(Tenant.slug.in_(slugs)))
        await db.commit()


async def purge_orphans() -> dict[str, int]:
    """Cleanup for orphans left by earlier generator versions — and the
    proof that they are gone.

    Sweeps EVERY public table carrying an event_id and/or tenant_id
    column (discovered from information_schema at runtime, so a new
    table can never be silently missed), deleting rows whose event or
    tenant no longer exists. Both criteria, on every table: event_orders
    has no foreign keys in the real schema, and rows can be orphaned at
    either level independently — staging held event-orphans whose tenant
    rows still existed, invisible to a tenant-only criterion. Tables
    whose FKs genuinely cascade simply contribute zero rows; sweeping
    them anyway costs nothing and closes the question.

    THE HARD PART, learned three rounds in: a printed number must be a
    POST-COMMIT FACT, not a statement's rowcount. rowcount reports what
    a statement affected inside its transaction, not what survived it.
    So after committing, this function opens a BRAND-NEW engine (its own
    connection pool, nothing shared with the session that deleted) and
    re-counts every orphan. It prints that verified number, and the
    caller exits non-zero if it is not zero. Whatever else can go wrong,
    the script can no longer report a cleanup the database disagrees
    with.

    Still behind the staging guard, still only via --purge-orphans.
    Returns {"removed": ..., "verified_remaining": ...}.
    """
    assert_staging()
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import settings as _settings
    from app.core.database import AsyncSessionLocal

    discover_sql = text("""
        SELECT c.table_name,
               bool_or(c.column_name = 'event_id')  AS has_event,
               bool_or(c.column_name = 'tenant_id') AS has_tenant
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_name = c.table_name AND t.table_schema = 'public'
        WHERE c.table_schema = 'public'
          AND t.table_type = 'BASE TABLE'
          AND c.column_name IN ('event_id', 'tenant_id')
          AND c.table_name NOT IN ('events', 'tenants')
        GROUP BY c.table_name
        ORDER BY c.table_name
    """)

    def _orphan_predicates(has_event: bool, has_tenant: bool) -> str:
        parts = []
        if has_event:
            # event_id can be nullable (e.g. system alerts) — NULL is
            # not an orphan.
            parts.append("(event_id IS NOT NULL AND NOT EXISTS "
                         "(SELECT 1 FROM events e WHERE e.id = x.event_id))")
        if has_tenant:
            parts.append("(NOT EXISTS "
                         "(SELECT 1 FROM tenants t WHERE t.id = x.tenant_id))")
        return " OR ".join(parts)

    async with AsyncSessionLocal() as db:
        tables = [(r.table_name, r.has_event, r.has_tenant)
                  for r in (await db.execute(discover_sql)).all()]
        removed_per_table: dict[str, int] = {}
        for name, has_event, has_tenant in tables:
            pred = _orphan_predicates(has_event, has_tenant)
            result = await db.execute(text(
                f'DELETE FROM "{name}" x WHERE {pred}'
            ))
            if result.rowcount:
                removed_per_table[name] = result.rowcount
        await db.commit()

    # Verification: a brand-new engine, NullPool, disposed after — a
    # connection that cannot be inside, or confused with, the deleting
    # session's transaction.
    verify_engine = create_async_engine(_settings.database_url, poolclass=NullPool)
    try:
        async with verify_engine.connect() as conn:
            remaining = 0
            for name, has_event, has_tenant in tables:
                pred = _orphan_predicates(has_event, has_tenant)
                remaining += (await conn.execute(text(
                    f'SELECT count(*) FROM "{name}" x WHERE {pred}'
                ))).scalar_one()
    finally:
        await verify_engine.dispose()

    removed = sum(removed_per_table.values())
    for name, count in sorted(removed_per_table.items()):
        print(f"  {name}: {count} removed")
    print(f"purged {removed} orphaned rows; "
          f"verified from a new connection: {remaining} orphaned rows remain")
    return {"removed": removed, "verified_remaining": remaining}


# ─── Builders ────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _create_tenants_and_users(db) -> dict[str, Any]:
    from app.core.security import hash_password
    from app.modules.auth.models import Tenant, User, UserRole, UserRoleAssignment
    from app.modules.venues.models import Venue

    tenants: dict[str, Tenant] = {}
    for name, slug in TENANTS:
        t = Tenant(name=name, slug=slug)
        db.add(t)
        await db.flush()
        db.add(Venue(
            tenant_id=t.id, name=f"{name} Venue", address="Staging, IT", capacity=5000,
        ))
        tenants[slug] = t

    users: dict[str, Any] = {}
    for email, password, role, slug in ACCOUNTS:
        user = User(
            tenant_id=tenants[slug].id,
            email=email,
            hashed_password=hash_password(password),
            full_name=email.split("@")[0].replace(".", " ").title(),
            role=UserRole(role),          # legacy column
            is_active=True,
        )
        db.add(user)
        await db.flush()
        # The AUTHORITATIVE role store — without this row the frontend
        # login flow rejects the account ("not authorized for this role").
        db.add(UserRoleAssignment(user_id=user.id, role=UserRole(role)))
        users[email] = user
    await db.flush()
    return {"tenants": tenants, "users": users}


def _product_category(name: str):
    from app.modules.products.models import ProductCategory

    return {
        "Spritz": ProductCategory.BASIC_COCKTAIL,
        "Gin Tonic": ProductCategory.BASIC_COCKTAIL,
        "Mojito": ProductCategory.BASIC_COCKTAIL,
        "Rum Cola": ProductCategory.BASIC_COCKTAIL,
        "Cocktail Premium": ProductCategory.PREMIUM_COCKTAIL,
        "Birra Media": ProductCategory.BEER_DRAFT,
        "Vino Bianco": ProductCategory.WINE_WHITE,
        "Vino Rosso": ProductCategory.WINE_RED,
    }.get(name, ProductCategory.SOFT_DRINK)


async def _create_catalog(db, tenant_id: UUID) -> dict[str, Any]:
    """Products mirroring the fake adapter's catalog, external_pos_id and
    all — the join the ingester depends on."""
    from app.modules.pos.adapters.fake import FAKE_PRODUCTS_RAW
    from app.modules.products.models import Product, ProductType, ProductUnit

    products: dict[str, Product] = {}
    for raw in FAKE_PRODUCTS_RAW:
        name = raw["name"]["it"]
        is_food = name in ("Panino", "Arancina")
        p = Product(
            tenant_id=tenant_id,
            name=name,
            product_type=ProductType.FOOD if is_food else ProductType.DRINK,
            category=None if is_food else _product_category(name),
            unit=ProductUnit.GLASS,
            default_price_cents=raw["defaultPrice"],
            external_pos_id=raw["_id"],
            is_archived=False,
        )
        db.add(p)
        products[raw["_id"]] = p
    await db.flush()
    return products


async def _create_bars(db, tenant_id: UUID, event_id: UUID) -> dict[str, Any]:
    """One bar per fake shop, created UNMAPPED.

    Shop mappings are set per event, only while that event needs them
    (_set_shop_mappings): the ingester resolves bars by
    (tenant, slesh_negozio_id) with NO event filter and LIMIT 1
    (order_ingester._find_bar_by_slesh_id), so the same shop id mapped
    on several events at once resolves ARBITRARILY — the exact
    BarNotInEventError storm the first staging live poll produced.
    History maps → ingests → unmaps each completed event in turn; the
    LIVE event is mapped last (minus Food Truck) and keeps the tenant's
    only live mappings."""
    from app.modules.bars.models import Bar
    from app.modules.pos.adapters.fake import FAKE_SHOPS_RAW

    bar_types = {
        "Bar Centrale": "drinks",
        "Bar Palco": "drinks",
        "Food Truck": "food",
        "Accrediti": "service",
    }
    bars: dict[str, Bar] = {}
    for raw in FAKE_SHOPS_RAW:
        bar = Bar(
            tenant_id=tenant_id,
            event_id=event_id,
            name=raw["name"],
            bar_type=bar_types[raw["name"]],
            is_active=True,
            slesh_negozio_id=None,
        )
        db.add(bar)
        bars[raw["_id"]] = bar
    await db.flush()
    return bars


async def _set_shop_mappings(db, event_id: UUID, *, include_food: bool = True,
                             clear: bool = False) -> None:
    """Map (or clear) this event's bars to the fake shop ids, by name.

    When include_food is False the Food Truck bar stays unmapped — its
    orders park in pending_shop_mappings and an operator can resolve
    them to this very bar through the UI (the Jul-19 rehearsal)."""
    from app.modules.bars.models import Bar
    from app.modules.pos.adapters.fake import FAKE_SHOPS_RAW

    by_name = {raw["name"]: raw["_id"] for raw in FAKE_SHOPS_RAW}
    bars = (await db.execute(
        select(Bar).where(Bar.event_id == event_id)
    )).scalars().all()
    for bar in bars:
        if clear:
            bar.slesh_negozio_id = None
        elif bar.name in by_name and (include_food or bar.name != "Food Truck"):
            bar.slesh_negozio_id = by_name[bar.name]
    await db.flush()


async def _create_event(
    db, tenant_id: UUID, venue_id: UUID, *, name: str, status,
    scheduled_at: datetime, scheduled_end_at: datetime,
    started_at: datetime | None = None, ended_at: datetime | None = None,
):
    from app.modules.events.models import Event

    e = Event(
        tenant_id=tenant_id,
        venue_id=venue_id,
        name=name,
        status=status,
        expected_guest_count=1500,
        scheduled_at=scheduled_at,
        scheduled_end_at=scheduled_end_at,
        started_at=started_at,
        ended_at=ended_at,
        version=1,
    )
    db.add(e)
    await db.flush()
    return e


async def _build_structure(db, *, fast: bool) -> dict[str, Any]:
    """Tenants, users, catalog, events in every state, bars."""
    from app.modules.events.models import EventStatus
    from app.modules.pos.adapters.fake import LOCAL_TZ
    from app.modules.venues.models import Venue

    out = await _create_tenants_and_users(db)
    tenants = out["tenants"]
    alpha, beta = tenants["staging-alpha"], tenants["staging-beta"]

    venues = {
        t.id: (await db.execute(
            select(Venue).where(Venue.tenant_id == t.id)
        )).scalars().first()
        for t in tenants.values()
    }

    out["products"] = await _create_catalog(db, alpha.id)

    window_minutes = 20 if fast else 180
    now = _now()
    completed = []
    for i, days_ago in enumerate((21, 14, 7), start=1):
        day = (now - timedelta(days=days_ago)).astimezone(LOCAL_TZ)
        start = day.replace(
            hour=LOCAL_EVENT_START_HOUR, minute=0, second=0, microsecond=0,
        )
        end = start + timedelta(minutes=window_minutes)
        e = await _create_event(
            db, alpha.id, venues[alpha.id].id,
            name=f"Alpha Notte {i}", status=EventStatus.COMPLETED,
            scheduled_at=start, scheduled_end_at=end,
            started_at=start, ended_at=end,
        )
        e.bars = await _create_bars(db, alpha.id, e.id)  # type: ignore[attr-defined]
        completed.append(e)

    live = await _create_event(
        db, alpha.id, venues[alpha.id].id,
        name="Alpha Live Night", status=EventStatus.LIVE,
        scheduled_at=now - timedelta(hours=1),
        scheduled_end_at=now + timedelta(days=7),
        started_at=now - timedelta(hours=1),
    )
    live.bars = await _create_bars(db, alpha.id, live.id)  # type: ignore[attr-defined]

    await _create_event(
        db, alpha.id, venues[alpha.id].id,
        name="Alpha Prossimo", status=EventStatus.ACTIVE,
        scheduled_at=now + timedelta(days=1),
        scheduled_end_at=now + timedelta(days=1, hours=8),
    )
    await _create_event(
        db, alpha.id, venues[alpha.id].id,
        name="Alpha Bozza", status=EventStatus.DRAFT,
        scheduled_at=now + timedelta(days=3),
        scheduled_end_at=now + timedelta(days=3, hours=8),
    )
    # Beta: draft only — deliberately NO completed events, so the
    # forecast's insufficient-history path runs instead of being assumed.
    await _create_event(
        db, beta.id, venues[beta.id].id,
        name="Beta Bozza", status=EventStatus.DRAFT,
        scheduled_at=now + timedelta(days=2),
        scheduled_end_at=now + timedelta(days=2, hours=8),
    )

    out["completed_events"] = completed
    out["live_event"] = live
    return out


# ─── History & rehearsal shapes ──────────────────────────────────────────────

async def _allocate_and_configure_stock(db, tenant_id: UUID, events, products) -> None:
    """bar_stock allocations (the depletion evaluator only counts stock
    lines that decremented a bar_stock row — allocations must exist
    BEFORE ingestion), plus recipes and the event_storage layer the
    read-time depletion view and inventory page consume."""
    from decimal import Decimal

    from app.modules.bar_stock.models import BarStock
    from app.modules.bars.models import Bar
    from app.modules.event_storage.models import (
        EventCategoryIngredient,
        EventStockBarAllocation,
        SupplierProduct,
    )
    from app.modules.products.models import Product, ProductType, ProductUnit
    from app.modules.recipes.models import Recipe, RecipeItem
    from app.modules.recipes.template_models import RecipeTemplate  # noqa: F401 — prime mapper

    # Recipe ingredients (bottle-level inputs the cascade decrements).
    ingredients: dict[str, Product] = {}
    for name in ("Prosecco 0.75", "Gin London Dry"):
        ing = Product(
            tenant_id=tenant_id, name=name,
            product_type=ProductType.INGREDIENT, category=None,
            unit=ProductUnit.BOTTLE, default_price_cents=0, is_archived=False,
        )
        db.add(ing)
        ingredients[name] = ing
    await db.flush()

    by_name = {p.name: p for p in products.values()}
    recipes = [
        ("Spritz", "Prosecco 0.75", Decimal("100")),
        ("Gin Tonic", "Gin London Dry", Decimal("50")),
    ]
    for drink_name, ing_name, ml in recipes:
        r = Recipe(
            tenant_id=tenant_id,
            drink_product_id=by_name[drink_name].id,
            yield_qty=Decimal("1"), yield_unit=ProductUnit.GLASS,
            display_name=f"{drink_name} (staging)",
        )
        db.add(r)
        await db.flush()
        db.add(RecipeItem(
            tenant_id=tenant_id, recipe_id=r.id,
            ingredient_product_id=ingredients[ing_name].id,
            qty=ml, unit=ProductUnit.ML,
        ))

    # bar_stock: every drink (deposits included) + ingredients at drinks
    # bars; food products at food bars. For every generated event.
    drink_rows = [p for p in products.values() if p.product_type == ProductType.DRINK]
    food_rows = [p for p in products.values() if p.product_type == ProductType.FOOD]
    for event in events:
        bars = (await db.execute(
            select(Bar).where(Bar.event_id == event.id)
        )).scalars().all()
        for bar in bars:
            pool: list[Product] = []
            if bar.bar_type == "drinks":
                pool = drink_rows + list(ingredients.values())
            elif bar.bar_type == "food":
                pool = food_rows
            for p in pool:
                db.add(BarStock(
                    tenant_id=tenant_id, event_id=event.id, bar_id=bar.id,
                    product_id=p.id, allocated_qty=Decimal("500"),
                    current_qty=Decimal("500"), returned_qty=Decimal("0"),
                ))
    await db.flush()

    # event_storage layer for the LIVE event (the last entry in events):
    # supplier products, dispatches, and per-product depletion rules.
    live = events[-1]
    suppliers = {}
    for sku, item, category, vol in (
        ("STG-PROS", "Prosecco 0.75L", "sparkling", 750),
        ("STG-GIN", "Gin London Dry 0.7L", "spirits", 700),
    ):
        sp = SupplierProduct(
            tenant_id=tenant_id, supplier_name="Staging Beverages Srl",
            supplier_sku=sku, item_name=item, category=category,
            default_unit="bottle", units_per_pack=6, volume_per_unit_ml=vol,
        )
        db.add(sp)
        suppliers[sku] = sp
    await db.flush()

    live_bars = (await db.execute(
        select(Bar).where(Bar.event_id == live.id, Bar.bar_type == "drinks")
    )).scalars().all()
    for bar in live_bars:
        for sp in suppliers.values():
            db.add(EventStockBarAllocation(
                tenant_id=tenant_id, event_id=live.id,
                supplier_product_id=sp.id, bar_id=bar.id,
                qty_allocated=Decimal("24"),
            ))
    rule_map = [
        ("Spritz", "STG-PROS", Decimal("100")),
        ("Gin Tonic", "STG-GIN", Decimal("50")),
        ("Cocktail Premium", "STG-GIN", Decimal("60")),
        ("Vino Bianco", "STG-PROS", Decimal("120")),
    ]
    for drink_name, sku, ml in rule_map:
        db.add(EventCategoryIngredient(
            tenant_id=tenant_id, event_id=live.id,
            slesh_category=drink_name.lower().replace(" ", "_"),
            product_id=by_name[drink_name].id,
            supplier_product_id=suppliers[sku].id,
            ml_per_sale=ml, bar_id=None,
            threshold_pct_warn=Decimal("70"), threshold_pct_empty=Decimal("90"),
        ))
    await db.flush()


async def _ingest_history(tenant_id: UUID, completed_events) -> dict[str, int]:
    """Run the fake adapter's order stream for each completed event's
    window through the REAL ingestion pipeline — same code path staging's
    worker runs live.

    Shop mappings are held by exactly ONE event at a time (map → ingest
    → unmap): the ingester's bar lookup is tenant-scoped, so concurrent
    mappings resolve arbitrarily across events."""
    from app.core.database import AsyncSessionLocal
    from app.modules.pos.adapters.fake import FakePOSAdapter
    from app.modules.pos.order_ingester import _LookupCache, ingest_order
    from app.modules.stock_transactions.service import StockTransactionService

    totals = {"orders": 0, "lines_ingested": 0, "lines_errors": 0}
    for event in completed_events:
        async with AsyncSessionLocal() as db:
            await _set_shop_mappings(db, event.id, include_food=True)
            service = StockTransactionService(db)
            cache = _LookupCache()
            async with FakePOSAdapter() as adapter:
                async for order in adapter.list_orders(
                    event.scheduled_at, event.scheduled_end_at, order_type=None,
                ):
                    r = await ingest_order(
                        db=db, order=order, event_id=event.id,
                        tenant_id=tenant_id, service=service, cache=cache,
                    )
                    totals["orders"] += 1
                    totals["lines_ingested"] += r.lines_ingested
                    totals["lines_errors"] += r.lines_errors
            await _set_shop_mappings(db, event.id, clear=True)
            await db.commit()
    return totals


async def _generate_reports(tenant_id: UUID, completed_events) -> int:
    """Reports for every completed event, both languages — then the two
    rehearsal shapes: DIVERGED language versions on event 2 (IT v1 with
    EN regenerated to v2; the asymmetry that surfaces the 22-Aug
    sibling-collision defect), and a FAILED regeneration row on event 3
    (ready v1 untouched + failed v2, the post-C5 shape)."""
    from app.core.database import AsyncSessionLocal
    from app.modules.reports.models import Report
    from app.modules.reports.service import ReportService

    count = 0
    async with AsyncSessionLocal() as db:
        service = ReportService(db)
        for event in completed_events:
            results = await service.generate_for_event_batch(tenant_id, event.id)
            count += len(results)

        # Diverged versions on the second completed event.
        target = completed_events[1]
        en_v1 = await service.repo.get_latest_for_event(tenant_id, target.id, "en")
        if en_v1 is not None and en_v1.status == "ready":
            await service.regenerate(tenant_id, en_v1.id, generated_by=None)
            count += 1

        # Failed regeneration shape on the third completed event.
        db.add(Report(
            tenant_id=tenant_id, event_id=completed_events[2].id,
            language="it", version=2, status="failed",
            failure_reason="staging fixture: simulated generation crash",
            generated_at=_now(),
        ))
        await db.commit()
    return count


async def _fit_forecasts(tenant_id: UUID) -> dict[str, str]:
    """Fit alpha's forecast models from its ingested completed events.
    Beta gets nothing — its insufficient-history path must stay live."""
    from app.core.database import AsyncSessionLocal
    from app.modules.predictions.demand.retrain import retrain_demand_model
    from app.modules.predictions.nowcast.retrain import retrain_from_completed_events

    out: dict[str, str] = {}
    async with AsyncSessionLocal() as db:
        try:
            r = await retrain_from_completed_events(
                db, tenant_id, triggered_by="staging_generator",
            )
            out["nowcast"] = str(r.get("status", r))
        except Exception as e:  # noqa: BLE001 — best-effort, surfaced in summary
            out["nowcast"] = f"error: {type(e).__name__}: {e}"
    async with AsyncSessionLocal() as db:
        try:
            r = await retrain_demand_model(
                db, tenant_id, triggered_by="staging_generator",
            )
            out["demand"] = str(r.get("status", r))
        except Exception as e:  # noqa: BLE001
            out["demand"] = f"error: {type(e).__name__}: {e}"
    return out


# ─── Entry points ────────────────────────────────────────────────────────────

async def build(*, fast: bool = False) -> dict[str, Any]:
    """Wipe the generator's tenants, rebuild everything. Returns summary
    counts. `fast` shrinks the ingestion windows for test runs."""
    assert_staging()
    await wipe()

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        state = await _build_structure(db, fast=fast)
        alpha = state["tenants"]["staging-alpha"]
        await _allocate_and_configure_stock(
            db, alpha.id,
            [*state["completed_events"], state["live_event"]],
            state["products"],
        )
        await db.commit()
        alpha_id = alpha.id
        completed = state["completed_events"]

    ingest_totals = await _ingest_history(alpha_id, completed)
    generator_tenant_ids = [t.id for t in state["tenants"].values()]

    # History done — the LIVE event takes the tenant's only mappings
    # (minus Food Truck: its orders park, resolvable via the UI).
    async with AsyncSessionLocal() as db:
        live_id = state["live_event"].id
        await _set_shop_mappings(db, live_id, include_food=False)
        await db.commit()

    await _generate_reports(alpha_id, completed)
    forecasts = await _fit_forecasts(alpha_id)

    # Summary counts are QUERIED, not claimed: every number below is
    # what actually landed in the database, so the printed summary can
    # never announce work that did not happen (the reported-vs-achieved
    # pattern this codebase keeps producing — docs/job-status-semantics.md).
    # orders/lines come from the ingester's own per-order results, which
    # are actuals already.
    from sqlalchemy import func

    from app.modules.auth.models import Tenant, User
    from app.modules.reports.models import Report

    async with AsyncSessionLocal() as db:
        tenants_in_db = (await db.execute(
            select(func.count()).select_from(Tenant).where(
                Tenant.slug.in_([slug for _n, slug in TENANTS])
            )
        )).scalar_one()
        accounts_in_db = (await db.execute(
            select(func.count()).select_from(User).where(
                User.email.in_([email for email, _p, _r, _s in ACCOUNTS])
            )
        )).scalar_one()
        reports_in_db = (await db.execute(
            select(func.count()).select_from(Report).where(
                Report.tenant_id.in_(generator_tenant_ids)
            )
        )).scalar_one()

    return {
        "tenants": tenants_in_db,
        "accounts": accounts_in_db,
        "completed_events": len(completed),
        "orders_ingested": ingest_totals["orders"],
        "lines_ingested": ingest_totals["lines_ingested"],
        "lines_errors": ingest_totals["lines_errors"],
        "reports": reports_in_db,
        "forecasts": forecasts,
    }


def main() -> None:
    p = argparse.ArgumentParser(prog="build_staging_data")
    p.add_argument("--fast", action="store_true",
                   help="short ingestion windows (used by the test suite)")
    p.add_argument("--purge-orphans", action="store_true",
                   help="also delete event_orders rows whose tenant no longer "
                        "exists — one-time cleanup for orphans left by earlier "
                        "generator versions (event_orders has no FKs in the "
                        "real schema; see wipe()'s docstring)")
    args = p.parse_args()

    async def _main() -> dict:
        # Purge and build MUST share one event loop: two asyncio.run()
        # calls share the async engine's connection pool across loops,
        # and the second crashes with "attached to a different loop" —
        # the run printed its purge count and then died before
        # rebuilding anything (Day-5 finding).
        if args.purge_orphans:
            purge_result = await purge_orphans()
            if purge_result["verified_remaining"] > 0:
                raise SystemExit(
                    f"PURGE FAILED VERIFICATION: {purge_result['verified_remaining']} "
                    "orphaned rows still present when re-counted from a new "
                    "connection after commit. Not proceeding to build."
                )
        return await build(fast=args.fast)

    summary = asyncio.run(_main())
    print("staging data built:", summary)
    print("accounts (email / password / role / tenant):")
    for email, password, role, slug in ACCOUNTS:
        print(f"  {email}  {password}  {role}  {slug}")
    sys.exit(0)


if __name__ == "__main__":
    main()
