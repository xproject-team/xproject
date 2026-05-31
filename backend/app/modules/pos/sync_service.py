"""Sync service — pulls reference data from Slesh into our local DB.

Used by:
  - app/scripts/sync_slesh_reference.py (B5 — one-shot CLI)
  - Future B6 polling worker (will reuse sync_shops at startup if needed)

Design:
  - Idempotent. Re-running is safe; it upserts via the external_pos_id
    (or slesh_negozio_id for shops) linkage column.
  - Two methods only — sync_shops + sync_products. Categories are an enum
    in our schema, not a table, so they don't sync.
  - Tenant-scoped. Every write is bound to a single tenant_id.
  - Non-mutating on Slesh side (read-only adapter, GET-only).

Spec: docs/slesh-integration-roadmap.md §B5
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models      import Bar
from app.modules.products.models  import Product, ProductCategory, ProductType, ProductUnit
from app.modules.pos.converters   import cents_to_decimal, localized_name

if TYPE_CHECKING:
    from app.modules.pos.adapters.slesh import SleshAdapter
    from app.modules.pos.schemas import Shop as SleshShop, Product as SleshProduct

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Result type — what each sync method returns
# ─────────────────────────────────────────────────────────────────────
@dataclass
class SyncResult:
    """Counts from a single sync pass — for logging and CLI output.

    `deactivated` was added when sync_shops gained the
    "missing-from-Slesh = set is_active=False" path. For sync_products
    (which doesn't have that path yet) it stays 0.
    """
    created:     int       = 0
    updated:     int       = 0
    skipped:     int       = 0
    deactivated: int       = 0
    errors:      list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.updated + self.skipped + self.deactivated

    def __str__(self) -> str:
        return (
            f"created={self.created} updated={self.updated} "
            f"skipped={self.skipped} deactivated={self.deactivated} "
            f"total={self.total}"
        )


# ─────────────────────────────────────────────────────────────────────
# Slesh category name → our ProductType discriminator
# Slesh has no DRINK subcategory info; drinks land with category=NULL
# and need manual classification in the UI later (B8).
# ─────────────────────────────────────────────────────────────────────
_SLESH_CATEGORY_TO_PRODUCT_TYPE: dict[str, ProductType | None] = {
    # exact-match Slesh category name -> our ProductType (or None to skip)
    "beverage":              ProductType.DRINK,
    "food":                  ProductType.FOOD,
    "merch":                 ProductType.SUPPLY,
    "guardaroba":            ProductType.SUPPLY,
    "prodotti non attivi":   None,    # disabled/inactive — skip during sync
}


def _classify_product_type(slesh_category_name: str | None) -> ProductType | None:
    """Map a Slesh category name to our ProductType discriminator.

    Returns None when:
      - The category name is recognised but represents 'inactive' / 'wardrobe'
        items we don't want to import.
      - The category is unknown (logged once, treated as skip).
    """
    if not slesh_category_name:
        return None
    key = slesh_category_name.strip().lower()
    if key in _SLESH_CATEGORY_TO_PRODUCT_TYPE:
        return _SLESH_CATEGORY_TO_PRODUCT_TYPE[key]
    # Unknown category — log once via warning. We default to None (skip).
    logger.warning(
        "sync: unknown Slesh category %r — product will be skipped. "
        "Update _SLESH_CATEGORY_TO_PRODUCT_TYPE in sync_service.py.",
        slesh_category_name,
    )
    return None


# ─────────────────────────────────────────────────────────────────────
# Shop sync — Slesh shops -> our `bars` table
# ─────────────────────────────────────────────────────────────────────
async def sync_shops(
    *,
    db:            AsyncSession,
    adapter:       "SleshAdapter",
    tenant_id:     UUID,
    event_id:      UUID,
    experience_id: str | None = None,
) -> SyncResult:
    """Pull shops from Slesh, upsert into bars table for the given event.

    Args:
        db:            Open async session.
        adapter:       Constructed SleshAdapter (credentials baked in).
        tenant_id:     Which tenant to scope the writes to.
        event_id:      Bars are tied to events; specify which one.
        experience_id: Optional Slesh experience filter.

    Returns:
        SyncResult with created/updated/skipped counts.
    """
    result = SyncResult()
    slesh_shops = await adapter.list_shops(experience_id=experience_id)
    logger.info("sync_shops: %d shops returned by Slesh", len(slesh_shops))

    for s in slesh_shops:
        # Look up by slesh_negozio_id (the linkage column on `bars`)
        existing = await _find_bar_by_slesh_id(db, tenant_id, s.id)

        if existing is None:
            bar = Bar(
                tenant_id        = tenant_id,
                event_id         = event_id,
                name             = s.name,
                slesh_negozio_id = s.id,
                bar_type         = "drinks",          # default, can be edited later
                is_active        = bool(s.is_enabled),
            )
            db.add(bar)
            result.created += 1
            logger.debug("sync_shops: created bar id=? name=%s slesh=%s",
                         s.name, s.id)
        else:
            # Update mutable fields (name + is_active). Linkage stays.
            changed = False
            if existing.name != s.name:
                existing.name = s.name
                changed = True
            if existing.is_active != bool(s.is_enabled):
                existing.is_active = bool(s.is_enabled)
                changed = True
            if changed:
                result.updated += 1
            else:
                result.skipped += 1

    # ── Deactivation pass: bars in OUR DB that Slesh no longer reports.
    # Slesh may have disabled or deleted a shop since last sync. We
    # never DELETE bars (FK chains: StockTransaction, BarStock, alerts,
    # chat etc. all reference bar_id) — we set is_active=False instead.
    # Re-activation happens automatically if Slesh sends the shop back.
    slesh_ids_seen = {str(s.id) for s in slesh_shops}
    stale_stmt = (
        select(Bar)
        .where(Bar.tenant_id == tenant_id)
        .where(Bar.event_id == event_id)
        .where(Bar.slesh_negozio_id.is_not(None))
        .where(Bar.is_active.is_(True))
    )
    stale_rows = (await db.execute(stale_stmt)).scalars().all()
    for bar in stale_rows:
        if bar.slesh_negozio_id not in slesh_ids_seen:
            bar.is_active = False
            result.deactivated += 1
            logger.info(
                "sync_shops: deactivated bar id=%s name=%s slesh=%s "
                "(no longer reported by Slesh)",
                bar.id, bar.name, bar.slesh_negozio_id,
            )

    await db.flush()
    logger.info("sync_shops: %s", result)
    return result


async def _find_bar_by_slesh_id(
    db: AsyncSession, tenant_id: UUID, slesh_id: str,
) -> Bar | None:
    stmt = (
        select(Bar)
        .where(Bar.tenant_id == tenant_id)
        .where(Bar.slesh_negozio_id == slesh_id)
        .limit(1)
    )
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


# ─────────────────────────────────────────────────────────────────────
# Product sync — Slesh products -> our `products` table
# ─────────────────────────────────────────────────────────────────────
async def sync_products(
    *,
    db:            AsyncSession,
    adapter:       "SleshAdapter",
    tenant_id:     UUID,
    experience_id: str | None = None,
) -> SyncResult:
    """Pull products from Slesh, upsert into products table.

    Skipped products: anything where the category maps to None (inactive
    items, unknown categories). Tracked in SyncResult.skipped.
    """
    result = SyncResult()
    # populated_field='category' tells Slesh to expand the category id
    # into the full Category object (so we can read the localized name).
    slesh_products = await adapter.list_products(
        experience_id   = experience_id,
        populated_field = "category",
    )
    logger.info("sync_products: %d products returned by Slesh", len(slesh_products))

    for p in slesh_products:
        # Resolve the category name from Slesh's response. The 'category'
        # field can be a populated dict OR a bare id string. We only
        # handle the populated case here — bare-string case can be
        # addressed in B7 if it shows up in real data.
        slesh_cat_name: str | None = None
        if p.category and not isinstance(p.category, str):
            slesh_cat_name = localized_name(
                p.category.name, locale="it", context=f"product {p.id}",
            )

        product_type = _classify_product_type(slesh_cat_name)
        if product_type is None:
            result.skipped += 1
            continue

        existing = await _find_product_by_external_id(db, tenant_id, p.id)
        prod_name = localized_name(p.name, locale="it", context=f"product {p.id}")

        # Compute price in cents (raw int, since our model uses default_price_cents)
        price_cents = p.default_price

        if existing is None:
            product = Product(
                tenant_id            = tenant_id,
                name                 = prod_name or "(unnamed)",
                product_type         = product_type,
                category             = None,            # see header comment
                tier_rank            = None,
                unit                 = ProductUnit.PIECE,  # safe default
                default_price_cents  = price_cents,
                external_pos_id      = p.id,
                is_archived          = False,
            )
            db.add(product)
            result.created += 1
        else:
            changed = False
            if existing.name != prod_name:
                existing.name = prod_name or "(unnamed)"
                changed = True
            if existing.default_price_cents != price_cents:
                existing.default_price_cents = price_cents
                changed = True
            if existing.product_type != product_type:
                existing.product_type = product_type
                changed = True
            if changed:
                result.updated += 1
            else:
                result.skipped += 1

    await db.flush()
    logger.info("sync_products: %s", result)
    return result


async def _find_product_by_external_id(
    db: AsyncSession, tenant_id: UUID, external_id: str,
) -> Product | None:
    stmt = (
        select(Product)
        .where(Product.tenant_id == tenant_id)
        .where(Product.external_pos_id == external_id)
        .limit(1)
    )
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


__all__ = [
    "SyncResult",
    "sync_shops",
    "sync_products",
]
