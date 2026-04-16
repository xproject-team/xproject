"""Database queries for the recipes module.

Two-table pattern, but most queries return Recipe with eager-loaded
items (via the selectin relationship configured on Recipe.items).
This avoids N+1 when listing recipes with their ingredient lines.

Direct item-CRUD (add/patch/remove individual ingredients) is exposed
for granular editing without refetching the whole recipe.
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recipes.models import Recipe, RecipeItem
from app.modules.recipes.schemas import (
    RecipeCreate,
    RecipeItemCreate,
    RecipeItemUpdate,
    RecipeUpdate,
)


class RecipeRepository:
    """SQL operations for recipes + recipe_items."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Recipe reads ─────────────────────────────────────────────────────────

    async def list_for_tenant(
        self,
        tenant_id: UUID,
    ) -> Sequence[Recipe]:
        """List all recipes for the tenant, each with items eager-loaded."""
        stmt = (
            select(Recipe)
            .where(Recipe.tenant_id == tenant_id)
            .order_by(Recipe.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().unique().all()

    async def get_by_id(
        self,
        tenant_id: UUID,
        recipe_id: UUID,
    ) -> Recipe | None:
        """Fetch a recipe with items eager-loaded. Tenant-scoped."""
        stmt = (
            select(Recipe)
            .where(Recipe.id == recipe_id)
            .where(Recipe.tenant_id == tenant_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_drink_product_id(
        self,
        tenant_id: UUID,
        drink_product_id: UUID,
    ) -> Recipe | None:
        """Fetch the recipe for a specific drink, if any."""
        stmt = (
            select(Recipe)
            .where(Recipe.tenant_id == tenant_id)
            .where(Recipe.drink_product_id == drink_product_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ─── Recipe writes ────────────────────────────────────────────────────────

    async def create_recipe(
        self,
        tenant_id: UUID,
        data: RecipeCreate,
    ) -> Recipe:
        """Insert a new recipe header. Items added separately."""
        recipe = Recipe(
            tenant_id=tenant_id,
            drink_product_id=data.drink_product_id,
            yield_qty=data.yield_qty,
            yield_unit=data.yield_unit,
            notes=data.notes,
        )
        self.db.add(recipe)
        await self.db.flush()
        await self.db.refresh(recipe)
        return recipe

    async def update_recipe(
        self,
        recipe: Recipe,
        data: RecipeUpdate,
    ) -> Recipe:
        """Apply partial update to a recipe header."""
        payload = data.model_dump(exclude_unset=True)
        for field, value in payload.items():
            setattr(recipe, field, value)
        self.db.add(recipe)
        await self.db.flush()
        await self.db.refresh(recipe)
        return recipe

    async def delete_recipe(self, recipe: Recipe) -> None:
        """Delete a recipe. CASCADE drops items. Hard delete is safe
        because recipes aren't referenced by transaction history yet —
        Step 6 reconciliation will use them read-only for depletion
        calculations."""
        await self.db.delete(recipe)
        await self.db.flush()

    # ─── Item reads ───────────────────────────────────────────────────────────

    async def get_item_by_id(
        self,
        tenant_id: UUID,
        item_id: UUID,
    ) -> RecipeItem | None:
        stmt = (
            select(RecipeItem)
            .where(RecipeItem.id == item_id)
            .where(RecipeItem.tenant_id == tenant_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def find_item_by_ingredient(
        self,
        recipe_id: UUID,
        ingredient_product_id: UUID,
    ) -> RecipeItem | None:
        """Dedup lookup before adding a new ingredient line."""
        stmt = (
            select(RecipeItem)
            .where(RecipeItem.recipe_id == recipe_id)
            .where(RecipeItem.ingredient_product_id == ingredient_product_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ─── Item writes ──────────────────────────────────────────────────────────

    async def create_item(
        self,
        tenant_id: UUID,
        recipe_id: UUID,
        data: RecipeItemCreate,
    ) -> RecipeItem:
        item = RecipeItem(
            tenant_id=tenant_id,
            recipe_id=recipe_id,
            ingredient_product_id=data.ingredient_product_id,
            qty=data.qty,
            unit=data.unit,
            note=data.note,
        )
        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def update_item(
        self,
        item: RecipeItem,
        data: RecipeItemUpdate,
    ) -> RecipeItem:
        payload = data.model_dump(exclude_unset=True)
        for field, value in payload.items():
            setattr(item, field, value)
        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def delete_item(self, item: RecipeItem) -> None:
        await self.db.delete(item)
        await self.db.flush()
