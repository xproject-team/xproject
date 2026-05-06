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
    display_name: str | None = Field(default=None, max_length=128)
    template_id:  UUID | None = None

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
    display_name: str | None = None
    template_id:  UUID | None = None
    items: list[RecipeItemResponse] = []

class RecipeItemCreateInPayload(BaseModel):
    """One ingredient line inside the atomic create payload.

    Same shape as RecipeItemCreate; declared separately so the schema is
    self-documenting (this one is "an item NESTED inside a parent payload"
    rather than "the body of POST /recipes/{id}/items").
    """
    ingredient_product_id: UUID
    qty:                   Decimal = Field(..., gt=0)
    unit:                  ProductUnit
    note:                  str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


class RecipeWithItemsCreate(BaseModel):
    """Atomic create payload — recipe header + ingredients in one shot.

    Service enforces every validation that POST /recipes and
    POST /recipes/{id}/items would have enforced separately, plus:
    - items list non-empty
    - no duplicate ingredient_product_id across the items list

    On any failure the entire transaction rolls back; no orphan recipe
    is left in the DB.

    Phase F.8e fields (optional):
      - display_name: bartender-facing label (defaults to drink Product name)
      - template_id:  reference to IBA template this recipe was built from
    """
    drink_product_id: UUID
    yield_qty:        Decimal = Field(default=Decimal("1"), gt=0)
    yield_unit:       ProductUnit
    notes:            str | None = Field(default=None, max_length=2000)
    display_name:     str | None = Field(default=None, max_length=128)
    template_id:      UUID | None = None
    items:            list[RecipeItemCreateInPayload] = Field(..., min_length=1)

    @field_validator("notes")
    @classmethod
    def _strip_notes(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None

    @field_validator("items")
    @classmethod
    def _no_duplicate_ingredients(cls, v: list["RecipeItemCreateInPayload"]) -> list["RecipeItemCreateInPayload"]:
        seen: set = set()
        for item in v:
            if item.ingredient_product_id in seen:
                raise ValueError(
                    f"Duplicate ingredient {item.ingredient_product_id} in items. "
                    f"Each ingredient can appear only once per recipe."
                )
            seen.add(item.ingredient_product_id)
        return v


# ─── Recipe templates (system-wide catalog, F.8) ──────────────────────────────

class RecipeTemplateItemResponse(BaseModel):
    """One ingredient line in a template — by logical role."""
    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: float},
    )
    id:               UUID
    template_id:      UUID
    ingredient_role:  str
    ingredient_label: str
    qty:              Decimal
    unit:             str
    order_index:      int


class RecipeTemplateResponse(BaseModel):
    """A canonical IBA-curated cocktail recipe.

    Tenant-free — every tenant sees the same catalog. The PER-TENANT layer
    is the existing `recipes` table, which (after F.8e) optionally references
    a `template_id` for traceability.
    """
    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: float},
    )
    id:          UUID
    slug:        str
    name:        str
    category:    str
    description: str | None = None
    glass_type:  str | None = None
    total_ml:    Decimal | None = None
    items:       list[RecipeTemplateItemResponse]

