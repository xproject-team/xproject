#!/usr/bin/env python3
"""seed_supplier_products.py — load supplier_products from a YAML manifest.

The YAML is the canonical source of truth for the master list. Edit it
when the supplier adds new items, re-run this loader, and the DB gets
in sync. Idempotent: re-running with no changes is a no-op; running
after edits only refreshes prices on existing rows (item_name, category,
units stay stable unless explicitly UPDATEd via the wizard).

Usage:
    python scripts/seed_supplier_products.py                    # Noma tenant, Partesa list
    python scripts/seed_supplier_products.py --dry-run          # print plan, no writes
    python scripts/seed_supplier_products.py --tenant-id XXX    # different tenant
    python scripts/seed_supplier_products.py --file path.yaml   # different manifest
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force full model registry (mirrors alembic/env.py)
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
from app.modules.event_storage.models import SupplierProduct, EventStockItem  # noqa: F401

from app.core.database import AsyncSessionLocal
from app.modules.event_storage.service import EventStorageService


# Noma Group tenant (Sundance owner)
DEFAULT_TENANT = UUID("25ef916c-a288-44ae-b17c-8dfd09390834")
DEFAULT_YAML = Path(__file__).resolve().parent.parent / "seeds" / "partesa_master_list.yaml"


async def seed(tenant_id: UUID, yaml_path: Path, dry_run: bool) -> None:
    data = yaml.safe_load(yaml_path.read_text())
    supplier_name = data.get("supplier", "Partesa")
    items = data.get("items", [])
    print(f"Loading {len(items)} items from {yaml_path.name}")
    print(f"  supplier : {supplier_name}")
    print(f"  tenant   : {tenant_id}")
    print(f"  dry-run  : {dry_run}")
    print()

    if not items:
        print("Manifest is empty. Nothing to do.")
        return

    async with AsyncSessionLocal() as db:
        service = EventStorageService(db)
        existing = await service.list_supplier_products(tenant_id)
        existing_by_sku = {sp.supplier_sku: sp for sp in existing}

        created = 0
        updated_price = 0
        unchanged = 0

        for item in items:
            sku = str(item["supplier_sku"])
            new_price = (
                Decimal(str(item["last_unit_price_eur"]))
                if item.get("last_unit_price_eur") is not None else None
            )
            label = f"[{sku:>20s}] {item['item_name']}"

            if sku in existing_by_sku:
                sp = existing_by_sku[sku]
                if new_price is not None and sp.last_unit_price_eur != new_price:
                    print(f"  UPDATE  {label}  "
                          f"€{sp.last_unit_price_eur} -> €{new_price}")
                    updated_price += 1
                    if not dry_run:
                        await service.upsert_supplier_product(
                            tenant_id,
                            supplier_sku=sku,
                            item_name=item["item_name"],
                            category=item["category"],
                            default_unit=item["default_unit"],
                            units_per_pack=item.get("units_per_pack", 1),
                            volume_per_unit_ml=item.get("volume_per_unit_ml"),
                            last_unit_price_eur=new_price,
                            supplier_name=supplier_name,
                        )
                else:
                    unchanged += 1
            else:
                print(f"  CREATE  {label}  €{new_price}")
                created += 1
                if not dry_run:
                    await service.upsert_supplier_product(
                        tenant_id,
                        supplier_sku=sku,
                        item_name=item["item_name"],
                        category=item["category"],
                        default_unit=item["default_unit"],
                        units_per_pack=item.get("units_per_pack", 1),
                        volume_per_unit_ml=item.get("volume_per_unit_ml"),
                        last_unit_price_eur=new_price,
                        supplier_name=supplier_name,
                    )

        if not dry_run:
            await db.commit()

        print()
        print(f"Summary: {created} created, {updated_price} price-updated, "
              f"{unchanged} unchanged.")
        if dry_run:
            print("(dry-run — no DB writes)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant-id", type=UUID, default=DEFAULT_TENANT)
    p.add_argument("--file", type=Path, default=DEFAULT_YAML)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(seed(args.tenant_id, args.file, args.dry_run))


if __name__ == "__main__":
    main()
