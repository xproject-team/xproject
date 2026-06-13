#!/usr/bin/env python3
"""bootstrap_noma.py — idempotent prod bootstrap for the Noma tenant.

Creates (if missing):
    1. Tenant row "Noma Group" with the canonical UUID
    2. Omar (Owner) user — login: omar@nomagroup.it / xproject2026
    3. All 31 supplier_products from Partesa invoice 5812120214

Safe to re-run. Existing rows are left alone.

Usage (inside Railway Console):
    python scripts/bootstrap_noma.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force model registry — needed so FKs resolve at flush time
from app.modules.auth.models import Tenant, User, UserRole  # noqa: F401
from app.modules.venues.models import Venue  # noqa: F401
from app.modules.events.models import Event  # noqa: F401
from app.modules.bars.models import Bar  # noqa: F401
from app.modules.products.models import Product  # noqa: F401
from app.modules.event_products.models import EventProduct  # noqa: F401
from app.modules.bar_stock.models import BarStock  # noqa: F401
from app.modules.recipes.models import Recipe, RecipeItem  # noqa: F401
from app.modules.stock_transactions.models import StockTransaction  # noqa: F401
from app.modules.chat.models import (  # noqa: F401
    ChatAttachment, Channel, ChannelMember, ChatMention, ChatMessage,
)
from app.modules.event_storage.models import SupplierProduct, EventStockItem  # noqa: F401

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from sqlalchemy import select


NOMA_TENANT_ID = UUID("25ef916c-a288-44ae-b17c-8dfd09390834")
OMAR_USER_ID   = UUID("abef43be-44c5-4041-94a4-09a265d71698")
OMAR_EMAIL     = "omar@nomagroup.it"
OMAR_PASSWORD  = "xproject2026"
OMAR_NAME      = "Omar Abdelbari El Asry"


async def main() -> None:
    async with AsyncSessionLocal() as session:
        # 1. Tenant
        tq = await session.execute(select(Tenant).where(Tenant.id == NOMA_TENANT_ID))
        tenant = tq.scalars().first()
        if tenant is None:
            tenant = Tenant(
                id=NOMA_TENANT_ID,
                name="Noma Group",
                slug="noma-group",
            )
            session.add(tenant)
            await session.flush()
            print(f"✓ Created tenant: Noma Group ({NOMA_TENANT_ID})")
        else:
            print(f"= Tenant already exists: {tenant.name}")

        # 2. Omar user (Owner)
        uq = await session.execute(select(User).where(User.id == OMAR_USER_ID))
        user = uq.scalars().first()
        if user is None:
            user = User(
                id=OMAR_USER_ID,
                tenant_id=NOMA_TENANT_ID,
                email=OMAR_EMAIL,
                hashed_password=hash_password(OMAR_PASSWORD),
                full_name=OMAR_NAME,
                role=UserRole.OWNER,
                is_active=True,
            )
            session.add(user)
            await session.flush()
            print(f"✓ Created user: {OMAR_EMAIL} (Owner)")
            print(f"  Password: {OMAR_PASSWORD}")
        else:
            print(f"= User already exists: {user.email}")

        await session.commit()

    print()
    print("=" * 60)
    print("✅ Bootstrap done.")
    print(f"   Login: {OMAR_EMAIL} / {OMAR_PASSWORD}")
    print("   Next: python scripts/seed_supplier_products.py")
    print("   Then: python scripts/setup_sundance_14_prod.py")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
