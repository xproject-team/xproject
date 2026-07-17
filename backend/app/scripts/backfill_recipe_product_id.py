"""CLI: backfill event_category_ingredients.product_id from slesh_category.

Root cause of the Sundance Jul-5 depletion outage: the depletion engine
joined stock_transactions to event_category_ingredients by matching
free-text slesh_category against product.name — two independently
maintained string namespaces that silently drifted apart. The permanent
fix adds a real FK (product_id, migration aa5). This script populates
that FK on existing rows so a later migration can make it NOT NULL.

Matching rules, in preference order, scoped to (tenant, active products):
  1. Exact byte-for-byte match: product.name == slesh_category
  2. Case-insensitive match: product.name.lower() == slesh_category.lower()
  3. If step 1 or 2 finds multiple candidates, but exactly ONE of them has
     product_type='drink' (the sellable item — supplier/warehouse "supply"
     shadow rows with the same name are not recipe targets), prefer it.
     Logged as PREFERRED-DRINK, not AMBIGUOUS.
  4. No match, or still ambiguous (0 or >1 'drink' candidates) -> leave
     product_id NULL, log the row to stderr for manual triage.

Idempotent — only considers rows where product_id IS NULL, so a second
run is a no-op for anything already resolved.

Usage:
    python -m app.scripts.backfill_recipe_product_id --dry-run --tenant-slug noma-group
    python -m app.scripts.backfill_recipe_product_id --tenant-slug noma-group
    python -m app.scripts.backfill_recipe_product_id --dry-run   # all tenants
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import column, select, table, update

from app.core.database import AsyncSessionLocal
from app.modules.auth.models import Tenant
from app.modules.event_storage.models import SupplierProduct
from app.modules.events.models import Event
from app.modules.products.models import Product, ProductType

# Core table reference for event_category_ingredients.product_id.
# Migration aa5 added this column to the DB; the ORM model
# (app/modules/event_storage/models.py) does not map it yet — that lands
# in Day 3 alongside the service-code cutover. Using Core here (instead
# of waiting on the ORM model) keeps this backfill script self-contained
# and out of scope for this session's file restrictions.
_eci = table(
    "event_category_ingredients",
    column("id"),
    column("tenant_id"),
    column("event_id"),
    column("slesh_category"),
    column("supplier_product_id"),
    column("product_id"),
)


@dataclass
class BackfillSummary:
    total:               int = 0
    matched_exact:       int = 0
    matched_ci:          int = 0
    preferred_drink:     int = 0
    unmatched:           list[dict] = field(default_factory=list)
    ambiguous:           list[dict] = field(default_factory=list)

    @property
    def matched(self) -> int:
        return self.matched_exact + self.matched_ci + self.preferred_drink


async def _resolve_tenant_ids(db, tenant_slug: str | None) -> list[UUID]:
    if tenant_slug is None:
        res = await db.execute(select(Tenant))
        tenants = list(res.scalars().all())
        if not tenants:
            raise SystemExit("❌ No tenants found in DB.")
        print(f"  No --tenant-slug given — running across all {len(tenants)} tenant(s).")
        return [t.id for t in tenants]

    res = await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
    tenant = res.scalar_one_or_none()
    if tenant is None:
        raise SystemExit(f"❌ Tenant {tenant_slug!r} not found.")
    print(f"  Resolved tenant: {tenant.name} (id={tenant.id})")
    return [tenant.id]


async def _load_product_maps(
    db, tenant_id: UUID,
) -> tuple[dict[str, list[Product]], dict[str, list[Product]]]:
    """Build (exact_name -> [products], lowercased_name -> [products]) maps
    for a tenant's active (non-archived) products. A name can map to more
    than one product (e.g. same name across different product_type rows,
    permitted by the DB's (tenant_id, name, product_type) unique index)."""
    res = await db.execute(
        select(Product)
        .where(Product.tenant_id == tenant_id)
        .where(Product.is_archived == False)  # noqa: E712
    )
    products = list(res.scalars().all())

    exact_map: dict[str, list[Product]] = {}
    ci_map: dict[str, list[Product]] = {}
    for p in products:
        exact_map.setdefault(p.name, []).append(p)
        ci_map.setdefault(p.name.lower(), []).append(p)
    return exact_map, ci_map


async def _load_context_names(
    db, tenant_id: UUID,
) -> tuple[dict[UUID, str], dict[UUID, str]]:
    """event_id -> event name, supplier_product_id -> item_name — for
    readable unmatched/ambiguous-row reporting."""
    event_res = await db.execute(select(Event.id, Event.name).where(Event.tenant_id == tenant_id))
    event_names = {row.id: row.name for row in event_res.all()}

    sp_res = await db.execute(
        select(SupplierProduct.id, SupplierProduct.item_name).where(
            SupplierProduct.tenant_id == tenant_id,
        )
    )
    sp_names = {row.id: row.item_name for row in sp_res.all()}
    return event_names, sp_names


async def _backfill_tenant(
    db, tenant_id: UUID, *, dry_run: bool, summary: BackfillSummary,
) -> None:
    res = await db.execute(
        select(
            _eci.c.id, _eci.c.event_id, _eci.c.slesh_category, _eci.c.supplier_product_id,
        ).where(
            _eci.c.tenant_id == tenant_id,
            _eci.c.product_id.is_(None),
        )
    )
    rows = list(res.all())
    if not rows:
        return

    exact_map, ci_map = await _load_product_maps(db, tenant_id)
    event_names, sp_names = await _load_context_names(db, tenant_id)

    # The reads above auto-began a transaction on this session (SQLAlchemy
    # 2.0 autobegin). End it here so each row below can open its own
    # session.begin() block — per-row transactions is a deliberate choice
    # (see module docstring) so a mid-run failure leaves prior rows
    # committed instead of rolling back the whole tenant's backfill.
    await db.commit()

    for row in rows:
        summary.total += 1
        cat = row.slesh_category
        row_ctx = {
            "row_id":       str(row.id),
            "slesh_category": cat,
            "tenant_id":    str(tenant_id),
            "event_id":     str(row.event_id),
            "event_name":   event_names.get(row.event_id, "(unknown event)"),
            "supplier_product_name": sp_names.get(row.supplier_product_id, "(unknown supplier product)"),
        }

        candidates = exact_map.get(cat)
        match_kind = "exact"
        if not candidates:
            candidates = ci_map.get(cat.lower())
            match_kind = "case-insensitive"

        if not candidates:
            summary.unmatched.append(row_ctx)
            print(
                f"UNMATCHED  row={row.id}  slesh_category={cat!r}  "
                f"tenant={tenant_id}  event={row_ctx['event_name']} ({row.event_id})",
                file=sys.stderr,
            )
            continue

        if len(candidates) > 1:
            drink_candidates = [p for p in candidates if p.product_type == ProductType.DRINK]
            if len(drink_candidates) != 1:
                row_ctx["candidate_product_ids"] = [str(p.id) for p in candidates]
                summary.ambiguous.append(row_ctx)
                print(
                    f"AMBIGUOUS  row={row.id}  slesh_category={cat!r}  "
                    f"tenant={tenant_id}  event={row_ctx['event_name']} ({row.event_id})  "
                    f"candidates={row_ctx['candidate_product_ids']}",
                    file=sys.stderr,
                )
                continue

            # Exactly one 'drink' candidate among the duplicates — the rest
            # are warehouse/inventory 'supply' shadow rows sharing the same
            # name, not recipe targets. Prefer the sellable drink.
            product = drink_candidates[0]
            other_ids = [str(p.id) for p in candidates if p.id != product.id]
            summary.preferred_drink += 1
            print(
                f"PREFERRED-DRINK  row={row.id}  slesh_category={cat!r}  "
                f"chosen={product.id}  skipped={other_ids}",
                file=sys.stderr,
            )
        else:
            product = candidates[0]
            if match_kind == "exact":
                summary.matched_exact += 1
            else:
                summary.matched_ci += 1

        if not dry_run:
            async with db.begin():
                await db.execute(
                    update(_eci).where(_eci.c.id == row.id).values(product_id=product.id)
                )


async def _run(args: argparse.Namespace) -> int:
    print()
    print("=" * 70)
    print(f"Recipe product_id backfill — tenant={args.tenant_slug or '(all)'}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'COMMIT (writing changes)'}")
    print("=" * 70)
    print()

    summary = BackfillSummary()
    async with AsyncSessionLocal() as db:
        tenant_ids = await _resolve_tenant_ids(db, args.tenant_slug)
        # End the implicit read transaction opened by _resolve_tenant_ids
        # before per-row session.begin() blocks start below.
        await db.commit()

        for tenant_id in tenant_ids:
            await _backfill_tenant(db, tenant_id, dry_run=args.dry_run, summary=summary)

    print()
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"  Total NULL rows examined: {summary.total}")
    print(f"  Matched (exact):          {summary.matched_exact}")
    print(f"  Matched (case-insensitive): {summary.matched_ci}")
    print(f"  Matched (preferred drink): {summary.preferred_drink}")
    print(f"  Ambiguous (skipped):      {len(summary.ambiguous)}")
    print(f"  Unmatched (skipped):      {len(summary.unmatched)}")
    print()

    if summary.ambiguous:
        print("  Ambiguous rows (multiple candidate products — needs manual triage):")
        for r in summary.ambiguous:
            print(
                f"    row={r['row_id']}  slesh_category={r['slesh_category']!r}  "
                f"event={r['event_name']}  candidates={r['candidate_product_ids']}"
            )
        print()

    if summary.unmatched:
        print("  Unmatched rows (no product found — needs manual triage):")
        for r in summary.unmatched:
            print(
                f"    row={r['row_id']}  slesh_category={r['slesh_category']!r}  "
                f"event={r['event_name']}  supplier_product={r['supplier_product_name']}"
            )
        print()

    if args.dry_run:
        print("=" * 70)
        print("DRY-RUN complete. No changes written.")
        print("Re-run without --dry-run to apply.")
        print("=" * 70)
    else:
        print("=" * 70)
        print(f"✅ Committed {summary.matched} row(s).")
        print("=" * 70)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill event_category_ingredients.product_id from slesh_category.",
    )
    parser.add_argument(
        "--tenant-slug",
        default=None,
        help="Tenant slug (e.g. noma-group). Default: run across all tenants.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing. Default is to write.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
