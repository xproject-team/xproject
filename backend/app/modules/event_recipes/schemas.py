"""Pydantic v2 request/response schemas for the event_recipes module.

Conventions: see app/modules/events/schemas.py docstring — Create
schemas for client input, Response schemas for server output.

Naming note: the underlying column is EventCategoryIngredient.slesh_category
(Slesh's product/category name, e.g. "SPRITZ APEROL", "GIN TONIC"). The API
renames it to `drink_name` for readability — Catalog's recipe editor is not
a Slesh-integration surface, it's "which bottle does this drink consume".
"""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EventRecipeRow(BaseModel):
    """One depletion rule: <drink_name> at <bar> consumes <ml_per_sale> ml
    of <supplier_product>. Denormalizes bar_name + supplier_product_name
    so the FE never has to cross-reference separate lookups.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    drink_name: str

    # bar_id is nullable at the DB level for rows seeded before the
    # Sundance 15 recipe editor (recipe_seeder.py / sundance_14_recipe.py
    # rows with bar_name=None meant "applies to every bar Slesh-side").
    # New rows created through this API always set bar_id (see
    # EventRecipeCreate.bar_id below) — Sundance 15's UI computes
    # total-event alerts by grouping per-bar rows at query time instead
    # of storing one all-bars row. GET still must surface the legacy
    # NULL-bar_id rows rather than silently hiding real recipe data, so
    # bar_id stays optional here and bar_name falls back to "All bars".
    bar_id: UUID | None
    bar_name: str

    supplier_product_id: UUID
    supplier_product_name: str

    ml_per_sale: float
    is_optional: bool


class EventRecipeListResponse(BaseModel):
    """GET /event-recipes/{event_id} response envelope."""
    rows: list[EventRecipeRow]
    # True once the event has left DRAFT — the FE locks the editor and
    # shows a read-only banner. Rows are still returned so Omar can see
    # (but not touch) what was configured before the event went live.
    read_only: bool


class EventRecipeCreate(BaseModel):
    """Payload for POST /event-recipes (single row) and the items of
    POST /event-recipes/bulk."""
    event_id: UUID
    drink_name: str = Field(..., min_length=1, max_length=128)
    # Required (unlike the DB column) — see EventRecipeRow.bar_id note.
    bar_id: UUID
    supplier_product_id: UUID
    ml_per_sale: float = Field(..., gt=0)
    is_optional: bool = False


class EventRecipePatch(BaseModel):
    """Payload for PATCH /event-recipes/{id}. Identity fields
    (drink_name/bar_id/supplier_product_id) are not editable — delete
    and recreate the row if those need to change."""
    ml_per_sale: float | None = Field(default=None, gt=0)
    is_optional: bool | None = None


class EventRecipeBulkCreate(BaseModel):
    """Payload for POST /event-recipes/bulk. Add-only — existing rows
    for the event are untouched; deletes go through DELETE per row."""
    event_id: UUID
    rows: list[EventRecipeCreate]


class EventRecipeItemError(BaseModel):
    """Validation failure for one row in a bulk payload."""
    index: int
    error: str
