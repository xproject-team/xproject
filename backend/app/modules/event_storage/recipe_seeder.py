"""Idempotent seeder for event_category_ingredients + sponsor supplier products.

Used by:
  - Simulator (setup() phase) for the sim event
  - Production seed script for real Sundance 14

Invocation:
    from app.modules.event_storage.recipe_seeder import seed_recipe_for_event
    from app.modules.event_storage.sundance_14_recipe import SUNDANCE_14_RECIPE
    await seed_recipe_for_event(session, tenant_id, event_id, SUNDANCE_14_RECIPE)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models import Bar
from app.modules.event_storage.models import (
    EventCategoryIngredient,
    EventStockBarAllocation,
    SupplierProduct,
)
from app.modules.event_storage.sundance_14_recipe import GIN_NO_3_SPONSOR

logger = logging.getLogger(__name__)


async def _resolve_supplier_product_id(
    session: AsyncSession,
    tenant_id: UUID,
    name_substring: str,
) -> UUID | None:
    """Resolve a supplier_product by case-insensitive item_name substring.

    Returns None if no match — caller decides how to handle (warn vs raise).
    """
    q = await session.execute(
        select(SupplierProduct).where(
            SupplierProduct.tenant_id == tenant_id,
            SupplierProduct.item_name.ilike(f"%{name_substring}%"),
        )
    )
    rows = list(q.scalars().all())
    if len(rows) == 0:
        return None
    if len(rows) > 1:
        logger.warning(
            "recipe_seeder: ambiguous name substring '%s' matched %d products: %s",
            name_substring, len(rows), [r.item_name for r in rows],
        )
    return rows[0].id


async def _resolve_bar_id(
    session: AsyncSession,
    tenant_id: UUID,
    event_id: UUID,
    bar_name: str,
) -> UUID | None:
    q = await session.execute(
        select(Bar.id).where(
            Bar.tenant_id == tenant_id,
            Bar.event_id == event_id,
            Bar.name == bar_name,
        )
    )
    return q.scalar_one_or_none()


async def ensure_gin_no_3_for_no3_bar(
    session: AsyncSession,
    tenant_id: UUID,
    event_id: UUID,
) -> tuple[UUID, UUID]:
    """Create GIN No 3 SupplierProduct + dispatch to NO.3 BAR if not yet present.

    Returns (supplier_product_id, allocation_id).
    """
    # 1. Find or create the sponsor SupplierProduct
    sku = GIN_NO_3_SPONSOR["supplier_sku"]
    q = await session.execute(
        select(SupplierProduct).where(
            SupplierProduct.tenant_id == tenant_id,
            SupplierProduct.supplier_sku == sku,
        )
    )
    sp = q.scalars().first()
    if sp is None:
        sp = SupplierProduct(
            tenant_id=tenant_id,
            supplier_name=GIN_NO_3_SPONSOR["supplier_name"],
            supplier_sku=sku,
            item_name=GIN_NO_3_SPONSOR["item_name"],
            category=GIN_NO_3_SPONSOR["category"],
            default_unit=GIN_NO_3_SPONSOR["default_unit"],
            units_per_pack=GIN_NO_3_SPONSOR["units_per_pack"],
            volume_per_unit_ml=GIN_NO_3_SPONSOR["volume_per_unit_ml"],
            last_unit_price_eur=GIN_NO_3_SPONSOR["last_unit_price_eur"],
        )
        session.add(sp)
        await session.flush()
        logger.info("recipe_seeder: created GIN No 3 sponsor SupplierProduct %s", sp.id)

    # 2. Resolve NO.3 BAR
    bar_id = await _resolve_bar_id(
        session, tenant_id, event_id, GIN_NO_3_SPONSOR["dispatch_to_bar"],
    )
    if bar_id is None:
        raise ValueError(
            f"GIN No 3 dispatch: bar '{GIN_NO_3_SPONSOR['dispatch_to_bar']}' "
            f"not found for event {event_id}"
        )

    # 3. Idempotent dispatch — check if already allocated this event
    qa = await session.execute(
        select(EventStockBarAllocation).where(
            EventStockBarAllocation.tenant_id == tenant_id,
            EventStockBarAllocation.event_id == event_id,
            EventStockBarAllocation.supplier_product_id == sp.id,
            EventStockBarAllocation.bar_id == bar_id,
        )
    )
    existing = qa.scalars().first()
    if existing is not None:
        return sp.id, existing.id

    alloc = EventStockBarAllocation(
        tenant_id=tenant_id,
        event_id=event_id,
        supplier_product_id=sp.id,
        bar_id=bar_id,
        qty_allocated=Decimal(str(GIN_NO_3_SPONSOR["total_bottles"])),
        notes="Sponsor — direct supply, not on Partesa invoice",
    )
    session.add(alloc)
    await session.flush()
    logger.info(
        "recipe_seeder: dispatched %d bottles of GIN No 3 to NO.3 BAR (alloc=%s)",
        GIN_NO_3_SPONSOR["total_bottles"], alloc.id,
    )
    return sp.id, alloc.id


async def seed_recipe_for_event(
    session: AsyncSession,
    tenant_id: UUID,
    event_id: UUID,
    recipe: list[tuple[str, str, float, str | None]],
) -> dict:
    """Idempotent. Returns counts: {created, skipped, unresolved_products, unresolved_bars}.

    For each (slesh_category, sku_substring, ml, bar_name_or_None):
      - Resolve supplier_product_id by ilike on item_name
      - Resolve bar_id by name (or NULL if not specified)
      - Insert EventCategoryIngredient if no row matches (event, category, sp, bar)
    """
    counts = {
        "created": 0, "skipped": 0,
        "unresolved_products": [], "unresolved_bars": [],
    }
    for slesh_category, name_sub, ml, bar_name in recipe:
        sp_id = await _resolve_supplier_product_id(session, tenant_id, name_sub)
        if sp_id is None:
            counts["unresolved_products"].append((slesh_category, name_sub))
            logger.warning(
                "recipe_seeder: no supplier_product matches '%s' (cat=%s) — skipping",
                name_sub, slesh_category,
            )
            continue

        bar_id: UUID | None = None
        if bar_name is not None:
            bar_id = await _resolve_bar_id(session, tenant_id, event_id, bar_name)
            if bar_id is None:
                counts["unresolved_bars"].append((slesh_category, bar_name))
                logger.warning(
                    "recipe_seeder: bar '%s' not found for event %s — skipping rule",
                    bar_name, event_id,
                )
                continue

        # Idempotency check
        existing_q = await session.execute(
            select(EventCategoryIngredient).where(
                EventCategoryIngredient.tenant_id == tenant_id,
                EventCategoryIngredient.event_id == event_id,
                EventCategoryIngredient.slesh_category == slesh_category,
                EventCategoryIngredient.supplier_product_id == sp_id,
                EventCategoryIngredient.bar_id == bar_id,
            )
        )
        if existing_q.scalars().first() is not None:
            counts["skipped"] += 1
            continue

        rule = EventCategoryIngredient(
            tenant_id=tenant_id,
            event_id=event_id,
            slesh_category=slesh_category,
            supplier_product_id=sp_id,
            ml_per_sale=Decimal(str(ml)),
            bar_id=bar_id,
        )
        session.add(rule)
        counts["created"] += 1

    await session.flush()
    logger.info("recipe_seeder for event=%s: %s", event_id, counts)
    return counts
