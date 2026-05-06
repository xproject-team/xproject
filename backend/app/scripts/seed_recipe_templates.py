"""Idempotent seed loader for the recipe template catalog.

Reads `app/modules/recipes/seeds/iba_cocktails.json` and upserts each
template by `slug`. Safe to re-run any time — re-seeding refreshes
data without duplicating rows.

Usage:
    PYTHONPATH=. python3 -m app.scripts.seed_recipe_templates

Designed to be safe on a live DB: each template is processed in its
own transaction, and the script never deletes anything we did not
just write.
"""
from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.modules.recipes.template_models import RecipeTemplate, RecipeTemplateItem

logger = logging.getLogger(__name__)


SEED_PATH = (
    Path(__file__).resolve().parent.parent
    / "modules" / "recipes" / "seeds" / "iba_cocktails.json"
)


def _compute_total_ml(items: list[dict]) -> Decimal | None:
    """Sum of qty for items whose unit is 'ml'. None if any non-ml unit
    appears (mixed units make the sum meaningless for sorting)."""
    total = Decimal("0")
    for it in items:
        if it.get("unit") != "ml":
            return None
        total += Decimal(str(it["qty"]))
    return total


async def _upsert_template(db: AsyncSession, t: dict) -> tuple[str, bool]:
    """Returns (slug, was_created). Idempotent — re-runs refresh in place."""
    res = await db.execute(
        select(RecipeTemplate).where(RecipeTemplate.slug == t["slug"])
    )
    existing = res.scalar_one_or_none()

    total_ml = _compute_total_ml(t["items"])

    if existing is None:
        # ── Create ──
        from datetime import datetime, timezone
        template = RecipeTemplate(
            id          = uuid4(),
            slug        = t["slug"],
            name        = t["name"],
            category    = t["category"],
            description = t.get("description"),
            glass_type  = t.get("glass_type"),
            total_ml    = total_ml,
            created_at  = datetime.now(tz=timezone.utc),
        )
        db.add(template)
        await db.flush()
        for idx, it in enumerate(t["items"]):
            db.add(RecipeTemplateItem(
                id               = uuid4(),
                template_id      = template.id,
                ingredient_role  = it["role"],
                ingredient_label = it["label"],
                qty              = Decimal(str(it["qty"])),
                unit             = it["unit"],
                order_index      = idx,
            ))
        return (t["slug"], True)

    # ── Refresh ── (preserve id, replace items)
    existing.name        = t["name"]
    existing.category    = t["category"]
    existing.description = t.get("description")
    existing.glass_type  = t.get("glass_type")
    existing.total_ml    = total_ml

    # Clear old items, write new ones — cleanest "make it match the JSON"
    for old_item in list(existing.items):
        await db.delete(old_item)
    await db.flush()

    for idx, it in enumerate(t["items"]):
        db.add(RecipeTemplateItem(
            id               = uuid4(),
            template_id      = existing.id,
            ingredient_role  = it["role"],
            ingredient_label = it["label"],
            qty              = Decimal(str(it["qty"])),
            unit             = it["unit"],
            order_index      = idx,
        ))
    return (t["slug"], False)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not SEED_PATH.exists():
        raise SystemExit(f"❌ seed file not found: {SEED_PATH}")

    payload = json.loads(SEED_PATH.read_text())
    templates = payload.get("templates", [])

    print(f"Seeding {len(templates)} recipe template(s) from {SEED_PATH.name}…")
    created = 0
    refreshed = 0

    async with AsyncSessionLocal() as db:
        for t in templates:
            slug, was_created = await _upsert_template(db, t)
            if was_created:
                created += 1
                print(f"  + created: {slug}")
            else:
                refreshed += 1
                print(f"  ~ refreshed: {slug}")
        await db.commit()

    print()
    print("=" * 60)
    print(f"✅ Done. {created} created, {refreshed} refreshed.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
