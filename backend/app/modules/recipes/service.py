"""Business logic for the recipes module.

Responsibilities:
1. Cross-module validation on recipe create:
   - drink_product exists, is not archived, is product_type=DRINK
   - no existing recipe for this drink in the tenant

2. Cross-module validation on item add:
   - recipe exists in tenant (tenant scoping)
   - ingredient_product exists in tenant, is not archived
   - ingredient_product != the drink of this recipe (no self-reference)
   - (recipe, ingredient) pair is unique (no duplicate ingredient lines)

3. Transaction boundaries:
   - Service commits at the end of each public method
   - Repository flushes but does not commit (§1.5)
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.products.models import ProductType
from app.modules.products.repository import ProductRepository
from app.modules.recipes.models import Recipe, RecipeItem
from app.modules.recipes.repository import RecipeRepository
from app.modules.recipes.schemas import (
    RecipeCreate,
    RecipeItemCreate,
    RecipeItemUpdate,
    RecipeUpdate,
    RecipeWithItemsCreate,
)


# ─── Domain exceptions ────────────────────────────────────────────────────────

class RecipeNotFoundError(Exception):
    """Recipe does not exist or tenant mismatch. -> 404."""


class RecipeItemNotFoundError(Exception):
    """Recipe item does not exist or tenant mismatch. -> 404."""


class DrinkProductNotFoundError(Exception):
    """drink_product_id in create doesn't exist. -> 404."""


class IngredientProductNotFoundError(Exception):
    """ingredient_product_id in item add doesn't exist. -> 404."""


class ProductArchivedError(Exception):
    """Attempt to reference an archived product (drink or ingredient). -> 422."""
    def __init__(self, message: str, product_role: str) -> None:
        super().__init__(message)
        self.product_role = product_role  # "drink" or "ingredient"


class NotADrinkError(Exception):
    """drink_product_id points to a non-DRINK product_type. -> 422."""
    def __init__(self, message: str, actual_type: str) -> None:
        super().__init__(message)
        self.actual_type = actual_type


class DuplicateRecipeError(Exception):
    """A recipe already exists for this drink in the tenant. -> 409."""
    def __init__(self, message: str, existing: Recipe) -> None:
        super().__init__(message)
        self.existing = existing


class SelfReferenceError(Exception):
    """An ingredient cannot be the same product as the recipe's drink. -> 422."""


class DuplicateIngredientError(Exception):
    """This ingredient is already in this recipe. -> 409."""
    def __init__(self, message: str, existing: RecipeItem) -> None:
        super().__init__(message)
        self.existing = existing


# ─── Service ──────────────────────────────────────────────────────────────────

class RecipeService:
    """All business logic for recipes + recipe_items."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = RecipeRepository(db)
        self.products = ProductRepository(db)

    # ─── Recipe reads ─────────────────────────────────────────────────────────

    async def list_recipes(self, tenant_id: UUID) -> Sequence[Recipe]:
        return await self.repo.list_for_tenant(tenant_id)

    async def get_recipe(self, tenant_id: UUID, recipe_id: UUID) -> Recipe:
        recipe = await self.repo.get_by_id(tenant_id, recipe_id)
        if recipe is None:
            raise RecipeNotFoundError(f"Recipe {recipe_id} not found")
        return recipe

    # ─── Recipe create / update / delete ──────────────────────────────────────

    async def create_recipe(
        self,
        tenant_id: UUID,
        data: RecipeCreate,
    ) -> Recipe:
        """Create a new recipe header. Items added separately."""
        # 1. Drink product exists?
        drink = await self.products.get_by_id(tenant_id, data.drink_product_id)
        if drink is None:
            raise DrinkProductNotFoundError(
                f"Product {data.drink_product_id} not found"
            )

        # 2. Not archived?
        if drink.is_archived:
            raise ProductArchivedError(
                f"Cannot create a recipe for archived product '{drink.name}'",
                product_role="drink",
            )

        # 3. Is actually a drink?
        if drink.product_type is not ProductType.DRINK:
            raise NotADrinkError(
                f"Product '{drink.name}' is a {drink.product_type.value}, "
                f"not a drink. Recipes can only be created for drinks.",
                actual_type=drink.product_type.value,
            )

        # 4. No existing recipe for this drink?
        existing = await self.repo.get_by_drink_product_id(
            tenant_id, data.drink_product_id,
        )
        if existing is not None:
            raise DuplicateRecipeError(
                f"A recipe already exists for '{drink.name}'. "
                f"Update the existing one or delete it first.",
                existing=existing,
            )

        # 5. Persist
        recipe = await self.repo.create_recipe(tenant_id, data)
        await self.db.commit()
        # Re-fetch to materialize items relationship as empty list
        return await self.get_recipe(tenant_id, recipe.id)

    async def update_recipe(
        self,
        tenant_id: UUID,
        recipe_id: UUID,
        data: RecipeUpdate,
    ) -> Recipe:
        recipe = await self.get_recipe(tenant_id, recipe_id)
        recipe = await self.repo.update_recipe(recipe, data)
        await self.db.commit()
        return await self.get_recipe(tenant_id, recipe.id)

    async def delete_recipe(
        self,
        tenant_id: UUID,
        recipe_id: UUID,
    ) -> None:
        recipe = await self.get_recipe(tenant_id, recipe_id)
        await self.repo.delete_recipe(recipe)
        await self.db.commit()

    # ─── Atomic create-with-items (F.7b) ─────────────────────────────────────

    async def create_recipe_with_items(
        self,
        tenant_id: UUID,
        data: RecipeWithItemsCreate,
    ) -> Recipe:
        """Create a recipe header + every ingredient line in ONE transaction.

        Re-runs every validation that the separate endpoints would have run:
        - drink exists, not archived, is product_type=DRINK
        - no existing recipe for this drink
        - each ingredient_product_id exists, is not archived
        - no ingredient equals the drink (self-reference)
        - no duplicate ingredient_product_id within the payload (Pydantic-checked)

        On any failure the SQLAlchemy session is rolled back and a typed
        exception is raised — no half-created recipe is left in the DB.
        """
        # ── 1. Validate the drink (same as create_recipe) ──
        drink = await self.products.get_by_id(tenant_id, data.drink_product_id)
        if drink is None:
            raise DrinkProductNotFoundError(
                f"Product {data.drink_product_id} not found"
            )
        if drink.is_archived:
            raise ProductArchivedError(
                f"Cannot create a recipe for archived product '{drink.name}'",
                product_role="drink",
            )
        if drink.product_type is not ProductType.DRINK:
            raise NotADrinkError(
                f"Product '{drink.name}' is a {drink.product_type.value}, "
                f"not a drink. Recipes can only be created for drinks.",
                actual_type=drink.product_type.value,
            )
        existing_recipe = await self.repo.get_by_drink_product_id(
            tenant_id, data.drink_product_id,
        )
        if existing_recipe is not None:
            raise DuplicateRecipeError(
                f"A recipe already exists for '{drink.name}'. "
                f"Update the existing one or delete it first.",
                existing=existing_recipe,
            )

        # ── 2. Pre-validate every ingredient BEFORE any write ──
        # We do this up front so a bad ingredient at index 4 doesn't leave
        # a recipe + 3 valid items in flight before we discover the failure.
        for item in data.items:
            ingredient = await self.products.get_by_id(
                tenant_id, item.ingredient_product_id,
            )
            if ingredient is None:
                raise IngredientProductNotFoundError(
                    f"Ingredient product {item.ingredient_product_id} not found"
                )
            if ingredient.is_archived:
                raise ProductArchivedError(
                    f"Cannot use archived product '{ingredient.name}' as an ingredient",
                    product_role="ingredient",
                )
            if item.ingredient_product_id == data.drink_product_id:
                raise SelfReferenceError(
                    "A recipe cannot contain itself as an ingredient."
                )

        # ── 3. Persist header + items in one transaction ──
        # We bypass create_recipe()'s internal commit by calling repo
        # directly. The single commit at the end ensures atomicity.
        try:
            recipe_create = RecipeCreate(
                drink_product_id = data.drink_product_id,
                yield_qty        = data.yield_qty,
                yield_unit       = data.yield_unit,
                notes            = data.notes,
                display_name     = data.display_name,
                template_id      = data.template_id,
            )
            recipe = await self.repo.create_recipe(tenant_id, recipe_create)
            # flush so we have recipe.id for the items
            await self.db.flush()

            for item in data.items:
                item_create = RecipeItemCreate(
                    ingredient_product_id = item.ingredient_product_id,
                    qty                   = item.qty,
                    unit                  = item.unit,
                    note                  = item.note,
                )
                await self.repo.create_item(tenant_id, recipe.id, item_create)

            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        # Re-fetch to materialize the items relationship for the response
        return await self.get_recipe(tenant_id, recipe.id)

    # ─── Item add / update / delete ───────────────────────────────────────────

    async def add_item(
        self,
        tenant_id: UUID,
        recipe_id: UUID,
        data: RecipeItemCreate,
    ) -> RecipeItem:
        """Add an ingredient line to a recipe.

        Validation chain: recipe exists -> ingredient exists -> not
        archived -> not self-reference -> not duplicate.
        """
        # 1. Recipe exists in tenant?
        recipe = await self.get_recipe(tenant_id, recipe_id)

        # 2. Ingredient exists?
        ingredient = await self.products.get_by_id(
            tenant_id, data.ingredient_product_id,
        )
        if ingredient is None:
            raise IngredientProductNotFoundError(
                f"Product {data.ingredient_product_id} not found"
            )

        # 3. Ingredient not archived?
        if ingredient.is_archived:
            raise ProductArchivedError(
                f"Cannot use archived product '{ingredient.name}' as an ingredient",
                product_role="ingredient",
            )

        # 4. Not the same as the drink (self-reference check)?
        if data.ingredient_product_id == recipe.drink_product_id:
            raise SelfReferenceError(
                "A recipe cannot contain itself as an ingredient."
            )

        # 5. Not already in this recipe?
        existing = await self.repo.find_item_by_ingredient(
            recipe_id, data.ingredient_product_id,
        )
        if existing is not None:
            raise DuplicateIngredientError(
                f"'{ingredient.name}' is already an ingredient in this recipe. "
                f"Update the existing line instead.",
                existing=existing,
            )

        item = await self.repo.create_item(tenant_id, recipe_id, data)
        await self.db.commit()
        return item

    async def update_item(
        self,
        tenant_id: UUID,
        item_id: UUID,
        data: RecipeItemUpdate,
    ) -> RecipeItem:
        item = await self.repo.get_item_by_id(tenant_id, item_id)
        if item is None:
            raise RecipeItemNotFoundError(f"Recipe item {item_id} not found")
        item = await self.repo.update_item(item, data)
        await self.db.commit()
        return item

    async def delete_item(
        self,
        tenant_id: UUID,
        item_id: UUID,
    ) -> None:
        item = await self.repo.get_item_by_id(tenant_id, item_id)
        if item is None:
            raise RecipeItemNotFoundError(f"Recipe item {item_id} not found")
        await self.repo.delete_item(item)
        await self.db.commit()
