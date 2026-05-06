"""HTTP router for the recipes module.

Endpoints (8 total):

Recipes:
    GET    /recipes                         list all (w/ items eager-loaded)
    GET    /recipes/{id}                    single recipe w/ items
    POST   /recipes                         create header
    PATCH  /recipes/{id}                    update header
    DELETE /recipes/{id}                    delete (CASCADE to items)

Recipe items (nested resource pattern):
    POST   /recipes/{recipe_id}/items       add ingredient line
    PATCH  /recipes/items/{item_id}         update line (tenant-scoped lookup)
    DELETE /recipes/items/{item_id}         remove line

URL design notes:
- POST on items requires {recipe_id} in path because creation needs
  to know WHICH recipe to attach to.
- PATCH/DELETE on items use /recipes/items/{item_id} because an item's
  id alone (plus tenant scoping) is sufficient to find it — and this
  avoids the awkward path /recipes/{recipe_id}/items/{item_id} where
  mismatched recipe_id and item_id would create confusion.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.recipes.schemas import (
    RecipeCreate,
    RecipeItemCreate,
    RecipeItemResponse,
    RecipeItemUpdate,
    RecipeResponse,
    RecipeUpdate,
    RecipeWithItemsResponse,
    RecipeWithItemsCreate,
    RecipeTemplateResponse)
from app.modules.recipes.service import (
    DrinkProductNotFoundError,
    DuplicateIngredientError,
    DuplicateRecipeError,
    IngredientProductNotFoundError,
    NotADrinkError,
    ProductArchivedError,
    RecipeItemNotFoundError,
    RecipeNotFoundError,
    RecipeService,
    SelfReferenceError,
)


async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return current_user.tenant_id


router = APIRouter()


# ─── Recipe endpoints ─────────────────────────────────────────────────────────

@router.get("", response_model=list[RecipeWithItemsResponse])
async def list_recipes(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> list[RecipeWithItemsResponse]:
    """List all recipes for the tenant with their ingredient lines."""
    service = RecipeService(db)
    recipes = await service.list_recipes(tenant_id)
    return [RecipeWithItemsResponse.model_validate(r) for r in recipes]


# ─── Recipe templates (read-only catalog, F.8d) ──────────────────────────────

@router.get(
    "/templates",
    response_model=list[RecipeTemplateResponse],
    summary="List the system-wide IBA cocktail catalog.",
)
async def list_recipe_templates(
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = None,
) -> list[RecipeTemplateResponse]:
    """Return the canonical recipe templates (system-seeded, read-only).

    Optionally filter by category (contemporary, unforgettable, new_era,
    shooter, wine, beer). Items are eager-loaded so this is one round-trip.

    Tenant-free — same catalog for every tenant.
    """
    from app.modules.recipes.template_models import RecipeTemplate

    stmt = select(RecipeTemplate).order_by(RecipeTemplate.name.asc())
    if category is not None:
        stmt = stmt.where(RecipeTemplate.category == category)

    res = await db.execute(stmt)
    templates = res.scalars().unique().all()
    return [RecipeTemplateResponse.model_validate(t) for t in templates]


@router.get("/{recipe_id}", response_model=RecipeWithItemsResponse)
async def get_recipe(
    recipe_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> RecipeWithItemsResponse:
    service = RecipeService(db)
    try:
        recipe = await service.get_recipe(tenant_id, recipe_id)
    except RecipeNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "recipe_not_found", "message": str(e)},
        )
    return RecipeWithItemsResponse.model_validate(recipe)


@router.post(
    "",
    response_model=RecipeWithItemsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_recipe(
    payload: RecipeCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> RecipeWithItemsResponse:
    """Create a recipe header. Items added via POST /recipes/{id}/items."""
    service = RecipeService(db)
    try:
        recipe = await service.create_recipe(tenant_id, payload)
    except DrinkProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "drink_product_not_found", "message": str(e)},
        )
    except ProductArchivedError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "product_archived",
                "message": str(e),
                "product_role": e.product_role,
            },
        )
    except NotADrinkError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "not_a_drink",
                "message": str(e),
                "actual_type": e.actual_type,
            },
        )
    except DuplicateRecipeError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_recipe",
                "message": str(e),
                "existing_id": str(e.existing.id),
            },
        )
    return RecipeWithItemsResponse.model_validate(recipe)


@router.patch("/{recipe_id}", response_model=RecipeWithItemsResponse)
async def update_recipe(
    recipe_id: UUID,
    payload: RecipeUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> RecipeWithItemsResponse:
    """Update recipe header. drink_product_id NOT patchable."""
    service = RecipeService(db)
    try:
        recipe = await service.update_recipe(tenant_id, recipe_id, payload)
    except RecipeNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "recipe_not_found", "message": str(e)},
        )
    return RecipeWithItemsResponse.model_validate(recipe)


@router.delete(
    "/{recipe_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_recipe(
    recipe_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> None:
    """Delete a recipe. CASCADE removes all its items."""
    service = RecipeService(db)
    try:
        await service.delete_recipe(tenant_id, recipe_id)
    except RecipeNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "recipe_not_found", "message": str(e)},
        )


# ─── Recipe item endpoints ────────────────────────────────────────────────────

@router.post(
    "/{recipe_id}/items",
    response_model=RecipeItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_recipe_item(
    recipe_id: UUID,
    payload: RecipeItemCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> RecipeItemResponse:
    """Add an ingredient line to a recipe.

    Error responses:
    - 404 recipe_not_found / ingredient_product_not_found
    - 422 product_archived / self_reference
    - 409 duplicate_ingredient (payload includes existing_id)
    """
    service = RecipeService(db)
    try:
        item = await service.add_item(tenant_id, recipe_id, payload)
    except RecipeNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "recipe_not_found", "message": str(e)},
        )
    except IngredientProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "ingredient_product_not_found", "message": str(e)},
        )
    except ProductArchivedError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "product_archived",
                "message": str(e),
                "product_role": e.product_role,
            },
        )
    except SelfReferenceError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "self_reference", "message": str(e)},
        )
    except DuplicateIngredientError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_ingredient",
                "message": str(e),
                "existing_id": str(e.existing.id),
            },
        )
    return RecipeItemResponse.model_validate(item)


@router.patch("/items/{item_id}", response_model=RecipeItemResponse)
async def update_recipe_item(
    item_id: UUID,
    payload: RecipeItemUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> RecipeItemResponse:
    """Update an ingredient line. ingredient_product_id NOT patchable."""
    service = RecipeService(db)
    try:
        item = await service.update_item(tenant_id, item_id, payload)
    except RecipeItemNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "recipe_item_not_found", "message": str(e)},
        )
    return RecipeItemResponse.model_validate(item)


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_recipe_item(
    item_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> None:
    """Remove an ingredient line from its recipe."""
    service = RecipeService(db)
    try:
        await service.delete_item(tenant_id, item_id)
    except RecipeItemNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "recipe_item_not_found", "message": str(e)},
        )


# ─── Atomic create-with-items (F.7b) ──────────────────────────────────────────
@router.post(
    "/with-items",
    response_model=RecipeWithItemsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a recipe + all its ingredient lines in a single transaction.",
)
async def create_recipe_with_items(
    payload: RecipeWithItemsCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> RecipeWithItemsResponse:
    """Atomic create — header + items, one transaction.

    Use this from forms that gather everything before a single Save click.
    For step-by-step UIs that add ingredients later, use POST /recipes
    + POST /recipes/{id}/items instead.

    Response body shape is identical to GET /recipes/{id} (RecipeWithItemsResponse).
    """
    service = RecipeService(db)
    try:
        recipe = await service.create_recipe_with_items(tenant_id, payload)
    except DrinkProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except IngredientProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProductArchivedError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except NotADrinkError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except DuplicateRecipeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except SelfReferenceError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return RecipeWithItemsResponse.model_validate(recipe)
