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
    """Delete the generator's two tenants (and, via FK cascade, every row
    they own). Never touches any other tenant. Guarded like build()."""
    assert_staging()
    from app.core.database import AsyncSessionLocal
    from app.modules.auth.models import Tenant

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Tenant).where(Tenant.slug.in_([slug for _n, slug in TENANTS]))
        )
        await db.commit()


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


async def _create_bars(db, tenant_id: UUID, event_id: UUID, *, unmap_food: bool) -> dict[str, Any]:
    """One bar per fake shop. When unmap_food is True the Food Truck bar
    is created WITHOUT its slesh_negozio_id — orders for that shop park
    in pending_shop_mappings, and an operator can resolve them to this
    very bar through the UI (the Jul-19 rehearsal)."""
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
        name = raw["name"]
        mapped = not (unmap_food and name == "Food Truck")
        bar = Bar(
            tenant_id=tenant_id,
            event_id=event_id,
            name=name,
            bar_type=bar_types[name],
            is_active=True,
            slesh_negozio_id=raw["_id"] if mapped else None,
        )
        db.add(bar)
        bars[raw["_id"]] = bar
    await db.flush()
    return bars


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
        e.bars = await _create_bars(db, alpha.id, e.id, unmap_food=False)  # type: ignore[attr-defined]
        completed.append(e)

    live = await _create_event(
        db, alpha.id, venues[alpha.id].id,
        name="Alpha Live Night", status=EventStatus.LIVE,
        scheduled_at=now - timedelta(hours=1),
        scheduled_end_at=now + timedelta(days=7),
        started_at=now - timedelta(hours=1),
    )
    live.bars = await _create_bars(db, alpha.id, live.id, unmap_food=True)  # type: ignore[attr-defined]

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


# ─── Entry points ────────────────────────────────────────────────────────────

async def build(*, fast: bool = False) -> dict[str, int]:
    """Wipe the generator's tenants, rebuild everything. Returns summary
    counts. `fast` shrinks the ingestion windows for test runs."""
    assert_staging()
    await wipe()

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        state = await _build_structure(db, fast=fast)
        await db.commit()

    return {
        "tenants": len(TENANTS),
        "accounts": len(ACCOUNTS),
        "completed_events": len(state["completed_events"]),
    }


def main() -> None:
    p = argparse.ArgumentParser(prog="build_staging_data")
    p.add_argument("--fast", action="store_true",
                   help="short ingestion windows (used by the test suite)")
    args = p.parse_args()
    summary = asyncio.run(build(fast=args.fast))
    print("staging data built:", summary)
    print("accounts (email / password / role / tenant):")
    for email, password, role, slug in ACCOUNTS:
        print(f"  {email}  {password}  {role}  {slug}")
    sys.exit(0)


if __name__ == "__main__":
    main()
