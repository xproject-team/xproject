#!/usr/bin/env python3
"""inject_stub.py — Phase 1 stub-flow verification helper.

Injects synthetic auto-created Bar rows for end-to-end testing of:
  - mapping-state polling picking up new stubs (~10s)
  - amber dashed border + NEEDS REVIEW pill rendering
  - inline name-picker dropdown (filtered by bar_type)
  - merge endpoint folding stub into wizard bar

Run from backend/ with venv active:

  python scripts/inject_stub.py inject
  python scripts/inject_stub.py inject --bar-type food
  python scripts/inject_stub.py inject --via-ingester
  python scripts/inject_stub.py list-stubs
  python scripts/inject_stub.py cleanup --bar-id <uuid>
  python scripts/inject_stub.py cleanup-all
"""
import argparse
import asyncio
import secrets
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from uuid import UUID

from sqlalchemy import select

# Force full SQLAlchemy model registry population (mirrors alembic/env.py)
# so FKs resolve when we flush Bar with FK -> events.id, etc.
from app.modules.auth.models import Tenant, User  # noqa: F401
from app.modules.venues.models import Venue  # noqa: F401
from app.modules.events.models import Event  # noqa: F401
from app.modules.products.models import Product  # noqa: F401
from app.modules.event_products.models import EventProduct  # noqa: F401
from app.modules.bar_stock.models import BarStock  # noqa: F401
from app.modules.recipes.models import Recipe, RecipeItem  # noqa: F401
from app.modules.stock_transactions.models import StockTransaction  # noqa: F401
from app.modules.chat.models import (  # noqa: F401
    ChatAttachment, Channel, ChannelMember, ChatMention, ChatMessage,
)

# Sundance 2026 / Noma Group
DEFAULT_TENANT = UUID("25ef916c-a288-44ae-b17c-8dfd09390834")
DEFAULT_EVENT = UUID("e7866455-b721-419e-8d10-e5e157ff50d6")


def random_shop_id() -> str:
    return secrets.token_hex(12)  # 24-char hex, mimics Mongo ObjectId


async def inject(tenant_id, event_id, bar_type, shop_id, via_ingester):
    from app.core.database import AsyncSessionLocal
    from app.modules.bars.models import Bar

    sid = shop_id or random_shop_id()

    async with AsyncSessionLocal() as db:
        if via_ingester:
            from app.modules.pos.order_ingester import _resolve_bar
            bar = await _resolve_bar(db, tenant_id, event_id, sid)
        else:
            display = f"{sid[:8]}…{sid[-4:]}" if len(sid) > 12 else sid
            bar = Bar(
                tenant_id=tenant_id,
                event_id=event_id,
                name=display,
                slesh_negozio_id=sid,
                bar_type=bar_type,
                is_active=True,
                auto_created=True,
            )
            db.add(bar)
            await db.flush()
        await db.commit()
        print("INJECTED STUB")
        print(f"  bar_id      : {bar.id}")
        print(f"  name        : {bar.name}")
        print(f"  bar_type    : {bar.bar_type}")
        print(f"  shop_id     : {bar.slesh_negozio_id}")
        print(f"  auto_created: {bar.auto_created}")
        print()
        print(f"Cleanup: python scripts/inject_stub.py cleanup --bar-id {bar.id}")


async def list_stubs(event_id):
    from app.core.database import AsyncSessionLocal
    from app.modules.bars.models import Bar

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Bar).where(
                Bar.event_id == event_id,
                Bar.auto_created.is_(True),
            )
        )).scalars().all()
        if not rows:
            print(f"No stubs in event {event_id}")
            return
        print(f"{len(rows)} stub(s) in event {event_id}:")
        for b in rows:
            print(f"  {b.id}  name={b.name!r}  bar_type={b.bar_type}  shop_id={b.slesh_negozio_id}")


async def cleanup(bar_id):
    from app.core.database import AsyncSessionLocal
    from app.modules.bars.models import Bar

    async with AsyncSessionLocal() as db:
        bar = (await db.execute(
            select(Bar).where(Bar.id == bar_id)
        )).scalar_one_or_none()
        if bar is None:
            print(f"Bar {bar_id} not found", file=sys.stderr)
            sys.exit(1)
        if not bar.auto_created:
            print(
                f"REFUSING to delete non-stub bar {bar_id} "
                f"(auto_created=False). Use the merge endpoint instead.",
                file=sys.stderr,
            )
            sys.exit(2)
        await db.delete(bar)
        await db.commit()
        print(f"Deleted stub {bar_id}")


async def cleanup_all(event_id):
    from app.core.database import AsyncSessionLocal
    from app.modules.bars.models import Bar

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Bar).where(
                Bar.event_id == event_id,
                Bar.auto_created.is_(True),
            )
        )).scalars().all()
        if not rows:
            print(f"No stubs to clean in event {event_id}")
            return
        for b in rows:
            await db.delete(b)
        await db.commit()
        print(f"Deleted {len(rows)} stub(s) from event {event_id}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("inject", help="Create a stub bar")
    pi.add_argument("--tenant-id", type=UUID, default=DEFAULT_TENANT)
    pi.add_argument("--event-id", type=UUID, default=DEFAULT_EVENT)
    pi.add_argument("--bar-type", choices=["drinks", "food"], default="drinks")
    pi.add_argument("--shop-id", type=str, default=None,
                    help="24-char hex shop_id (random if omitted)")
    pi.add_argument("--via-ingester", action="store_true",
                    help="Use _resolve_bar (production path; forces drinks)")

    pl = sub.add_parser("list-stubs", help="List all auto-created stubs")
    pl.add_argument("--event-id", type=UUID, default=DEFAULT_EVENT)

    pc = sub.add_parser("cleanup", help="Delete one stub by id")
    pc.add_argument("--bar-id", type=UUID, required=True)

    pca = sub.add_parser("cleanup-all", help="Delete all stubs in an event")
    pca.add_argument("--event-id", type=UUID, default=DEFAULT_EVENT)

    a = p.parse_args()

    if a.cmd == "inject":
        asyncio.run(inject(a.tenant_id, a.event_id, a.bar_type, a.shop_id, a.via_ingester))
    elif a.cmd == "list-stubs":
        asyncio.run(list_stubs(a.event_id))
    elif a.cmd == "cleanup":
        asyncio.run(cleanup(a.bar_id))
    elif a.cmd == "cleanup-all":
        asyncio.run(cleanup_all(a.event_id))


if __name__ == "__main__":
    main()
