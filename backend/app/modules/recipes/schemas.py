"""Pydantic v2 schemas for the recipes module.

Structure:
- Recipe header schemas: RecipeCreate, RecipeUpdate, RecipeResponse
- Recipe item schemas:   RecipeItemCreate, RecipeItemUpdate, RecipeItemResponse
- Composite:             RecipeWithItemsResponse (header + items array)

The GET endpoints return nested RecipeWithItemsResponse so clients see
the complete recipe in one round-trip. Items-only CRUD endpoints let
bartenders edit individual lines without refetching the whole recipe.

Units:
- Decimals are serialized as strings by default in Pydantic v2 to
  preserve precision. We override with float encoding for usability
  in the JS frontend (fractional qty as number, not "50.000").
"""
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.products.models import ProductUnit


# ─── Recipe item schemas ──────────────────────────────────────────────────────

class RecipeItemResponse(BaseModel):
    """Single ingredient line."""
    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: float},
    )

    id: UUID
    recipe_id: UUID
    ingredient_product_id: UUID
    qty: Decimal = Field(..., gt=0)
    unit: ProductUnit
    note: str | None = None


class RecipeItemCreate(BaseModel):
    """Payload for POST /recipes/{recipe_id}/items.

    Service enforces:
    - ingredient_product_id exists and is not archived
    - ingredient_product_id != the recipe's drink_product_id
      (cannot contain itself)
    - (recipe_id, ingredient_product_id) triple unique
    """
    ingredient_product_id: UUID
    qty: Decimal = Field(..., gt=0, description="Positive quantity.")
    unit: ProductUnit
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


class RecipeItemUpdate(BaseModel):
    """PATCH /recipes/{recipe_id}/items/{id}.

    ingredient_product_id is NOT patchable (delete + re-add if you need
    to change which ingredient a line points to).
    """
    qty: Decimal | None = Field(default=None, gt=0)
    unit: ProductUnit | None = None
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


# ─── Recipe header schemas ────────────────────────────────────────────────────

class RecipeCreate(BaseModel):
    """Create a recipe for a drink. Items are added separately via
    the items endpoints after creation, keeping the create payload small.

    Service enforces:
    - drink_product_id exists, is not archived, and is product_type=DRINK
    - No existing recipe for this drink in the tenant
    """
    drink_product_id: UUID
    yield_qty: Decimal = Field(default=Decimal("1"), gt=0)
    yield_unit: ProductUnit
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("notes")
    @classmethod
    def _strip_notes(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


class RecipeUpdate(BaseModel):
    """PATCH /recipes/{id}. drink_product_id is NOT patchable (delete +
    recreate if you need to repoint to a different drink)."""
    yield_qty: Decimal | None = Field(default=None, gt=0)
    yield_unit: ProductUnit | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("notes")
    @classmethod
    def _strip_notes(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


class RecipeResponse(BaseModel):
    """Header-only recipe response (no items)."""
    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: float},
    )

    id: UUID
    drink_product_id: UUID
    yield_qty: Decimal
    yield_unit: ProductUnit
    notes: str | None = None


# ─── Composite: header + items ────────────────────────────────────────────────

class RecipeWithItemsResponse(BaseModel):
    """Full recipe with nested items list.

    Returned by GET /recipes and GET /recipes/{id}. Items are eager-
    loaded at the ORM level (selectin strategy) so no N+1 queries.
    """
    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: float},
    )

    id: UUID
    drink_product_id: UUID
    yield_qty: Decimal
    yield_unit: ProductUnit
    notes: str | None = None
    items: list[RecipeItemResponse]
