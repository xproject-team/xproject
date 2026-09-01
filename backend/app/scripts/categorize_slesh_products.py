"""CLI: classify Slesh-synced products with category + tier_rank.

The Slesh sync pulls product names and prices but leaves category and
tier_rank NULL. This script applies deterministic name-based classification
based on the catalog patterns observed in Sundance 2024 and 2025 data.

Idempotent. Dry-run by default. Use --commit to actually write.

Usage:
    python -m app.scripts.categorize_slesh_products --tenant-slug noma-group
    python -m app.scripts.categorize_slesh_products --tenant-slug noma-group --commit
"""
from __future__ import annotations

import app.models_registry  # noqa: F401 — complete the FK graph for standalone runs

import argparse
import asyncio
import sys
from uuid import UUID

from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.modules.auth.models import Tenant
from app.modules.products.models import Product


# Classification table.  Each rule: (name_match, product_type, category, tier_rank, unit)
# Justifications baked into comments.  Conservative defaults; better to leave NULL than guess wrong.
RULES: list[tuple[str, str, str | None, int | None, str | None]] = [
    # Cup deposit — not a drink, reclassify as supply.  No category needed.
    ("Bicchiere",                "supply", None,                None, "piece"),
    # Gelato is FOOD, not a drink.  Reclassify product_type.
    ("Gelato",                   "food",   None,                None, "piece"),
    # Water — clearly soft_drink tier 1
    ("Acqua",                    "drink",  "soft_drink",         1, None),
    ("Soft Drink",               "drink",  "soft_drink",         1, None),
    # Beers — bottle category, tier 1 (commodity beer)
    ("Nastro Azzurro",           "drink",  "beer_bottle",        1, None),
    ("Raffo",                    "drink",  "beer_bottle",        1, None),
    # Cocktails — name-based tier inference
    ("Cocktail",                 "drink",  "basic_cocktail",     2, None),
    ("Cocktail signature",       "drink",  "basic_cocktail",     2, None),
    ("Cocktail Super premium",   "drink",  "premium_cocktail",   3, None),
    ("Sprtiz",                   "drink",  "basic_cocktail",     2, None),
    # Wine
    ("Bottiglia Vino",           "drink",  "wine_red",           3, None),
    ("Vino e bolle",             "drink",  "wine_sparkling",     2, None),
    # Other
    ("Shot",                     "drink",  "premium_cocktail",   3, None),
    # Analcolico is non-alcoholic cocktail — there's no exact enum so basic_cocktail tier 2.
    # When we add a non_alcoholic_cocktail enum later, update this row.
    ("Analcolico",               "drink",  "basic_cocktail",     2, None),
]


async def _resolve_tenant_id(db, slug: str) -> UUID:
    res = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = res.scalar_one_or_none()
    if tenant is None:
        raise SystemExit(f"❌ Tenant {slug!r} not found.")
    print(f"  Resolved tenant: {tenant.name} (id={tenant.id})")
    return tenant.id


async def _run(args: argparse.Namespace) -> int:
    print()
    print("=" * 70)
    print(f"Slesh product categorization — tenant={args.tenant_slug}")
    print(f"Mode: {'COMMIT' if args.commit else 'DRY-RUN (use --commit to apply)'}")
    print("=" * 70)
    print()

    async with AsyncSessionLocal() as db:
        tenant_id = await _resolve_tenant_id(db, args.tenant_slug)

        # Build a map of current products by name
        res = await db.execute(
            select(Product).where(Product.tenant_id == tenant_id)
                           .where(Product.is_archived == False)  # noqa: E712
        )
        all_products = list(res.scalars().all())
        # Map by stripped name for tolerant lookup; original kept on the row
        products = {p.name.strip(): p for p in all_products}

        # Flag any rows that have trailing/leading whitespace — those need fixing
        whitespace_fixes: list = []
        for p in all_products:
            if p.name != p.name.strip():
                whitespace_fixes.append(p)

        print(f"  Loaded {len(products)} active products from DB")
        if whitespace_fixes:
            print(f"  Found {len(whitespace_fixes)} products with whitespace in name (will be trimmed)")
        print()

        # Plan changes
        changes: list[tuple[Product, dict]] = []
        skipped: list[str] = []
        not_found: list[str] = []

        for name, ptype, category, tier, unit in RULES:
            p = products.get(name)
            if p is None:
                not_found.append(name)
                continue
            # Compute the diff
            updates: dict = {}
            if p.product_type.value != ptype:
                updates["product_type"] = ptype
            if category is not None and p.category != category:
                # SQLAlchemy enum compare: p.category may be None
                if p.category is None or p.category.value != category:
                    updates["category"] = category
            if tier is not None and p.tier_rank != tier:
                updates["tier_rank"] = tier
            if unit is not None and p.unit.value != unit:
                updates["unit"] = unit
            if updates:
                changes.append((p, updates))
            else:
                skipped.append(name)

        # DEFERRED: whitespace-trim is NOT applied here.
        # Reason: blindly stripping names risks UNIQUE constraint violations
        # for product names that have a clean-name twin already in DB
        # (e.g. "Arancine " trims to "Arancine" which already exists).
        # Dedup requires checking FK references first; that's a separate
        # script in a separate commit.  See: PHASE_2_DEDUP.md (TODO).
        if whitespace_fixes:
            print(f"  NOTE: {len(whitespace_fixes)} products have whitespace in name "
                  f"but are NOT being trimmed in this script.")
            print(f"        Whitespace cleanup is deferred to a separate dedup phase.")
            for wp in whitespace_fixes:
                print(f"        DEFER   '{wp.name}' (id={wp.id})")
            print()

        # Report
        print(f"  Planned changes: {len(changes)}")
        for p, updates in changes:
            change_str = ", ".join(f"{k}={v}" for k, v in updates.items())
            print(f"    UPDATE  {p.name:30s}  ->  {change_str}")
        print()
        if skipped:
            print(f"  Already correct (skipped): {len(skipped)}")
            for name in skipped:
                print(f"    SKIP    {name}")
            print()
        if not_found:
            print(f"  Not found in DB: {len(not_found)}")
            for name in not_found:
                print(f"    MISS    {name}")
            print()

        if not args.commit:
            print("=" * 70)
            print("DRY-RUN complete.  No changes written.")
            print("Re-run with --commit to apply.")
            print("=" * 70)
            return 0

        # Apply
        print("Applying changes...")
        for p, updates in changes:
            for k, v in updates.items():
                setattr(p, k, v)
        await db.commit()
        print(f"✅ Committed {len(changes)} updates.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Categorize Slesh-synced products.")
    parser.add_argument("--tenant-slug", required=True,
                        help="Tenant slug (e.g. noma-group).")
    parser.add_argument("--commit", action="store_true",
                        help="Actually apply changes.  Default is dry-run.")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
