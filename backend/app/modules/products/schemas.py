"""Pydantic v2 request/response schemas for the products module.

Conventions:
- Response: tenant_id omitted (client is already scoped via JWT)
- Create: all required fields; tier_rank auto-derived if null + drink + category
- Update: all optional; caller can explicitly null-out overridable fields

Validation strategy:
- Python enums as Pydantic fields — FastAPI auto-generates OpenAPI enum lists
- tier_rank validated at model constraint + schema bounds (1-4)
- default_price_cents validated ≥ 0
- Category coherence (only drinks have category/tier_rank) enforced at
  the service layer, NOT the schema — keeps schemas dumb, services smart
"""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.products.models import (
    CATEGORY_DEFAULT_TIER_RANK,
    ProductCategory,
    ProductType,
    ProductUnit,
)


# ─── Response ─────────────────────────────────────────────────────────────────

class ProductResponse(BaseModel):
    """Shape returned by GET /api/v1/products and related endpoints."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    product_type: ProductType
    category: ProductCategory | None = None
    tier_rank: int | None = Field(default=None, ge=1, le=4)
    unit: ProductUnit
    default_price_cents: int | None = Field(default=None, ge=0)
    external_pos_id: str | None = None
    barcode: str | None = None
    iva_pct: float | None = None
    cauzione_cents: int | None = None
    is_archived: bool


# ─── Create ───────────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    """Payload for POST /api/v1/products.

    Rules enforced downstream by service.create_product:
    - product_type=DRINK  → category REQUIRED, tier_rank derived if null
    - product_type!=DRINK → category MUST be null, tier_rank MUST be null
    """
    name: str = Field(..., min_length=1, max_length=255)
    product_type: ProductType
    category: ProductCategory | None = None
    tier_rank: int | None = Field(default=None, ge=1, le=4)
    unit: ProductUnit
    default_price_cents: int | None = Field(default=None, ge=0)
    external_pos_id: str | None = Field(default=None, max_length=128)
    iva_pct: float | None = Field(default=None, ge=0, le=1)
    cauzione_cents: int | None = Field(default=None, ge=0)
    barcode: str | None = Field(
        default=None,
        max_length=64,
        description="EAN-13/UPC-A/Code-128 barcode for scanner lookup. Per-tenant unique.",
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        """Trim whitespace on save so 'House Mojito ' and 'House Mojito' don't
        end up as duplicates that slip past the partial unique index."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("name cannot be blank after trimming")
        return stripped


# ─── Update ───────────────────────────────────────────────────────────────────

class ProductUpdate(BaseModel):
    """Payload for PATCH /api/v1/products/{id}. All fields optional.

    Fields NOT patchable:
    - product_type (changing type retroactively invalidates downstream refs)
    - is_archived  (use /archive and /restore endpoints instead)

    Archive/restore are separate endpoints to make the state change explicit
    and searchable in logs/audit.
    """
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: ProductCategory | None = None
    tier_rank: int | None = Field(default=None, ge=1, le=4)
    unit: ProductUnit | None = None
    default_price_cents: int | None = Field(default=None, ge=0)
    external_pos_id: str | None = Field(default=None, max_length=128)
    barcode: str | None = Field(default=None, max_length=64)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("name cannot be blank after trimming")
        return stripped


# ─── Helpers ──────────────────────────────────────────────────────────────────

def derive_tier_rank(
    product_type: ProductType,
    category: ProductCategory | None,
    explicit: int | None,
) -> int | None:
    """Resolve tier_rank for a drink given the Create/Update payload.

    Rules:
    - Not a drink → always None (even if caller passes one — strip it)
    - Drink + explicit tier_rank → use the explicit value (override)
    - Drink + category only     → derive from CATEGORY_DEFAULT_TIER_RANK
    - Drink + no category       → None (let service validation reject it)
    """
    if product_type is not ProductType.DRINK:
        return None
    if explicit is not None:
        return explicit
    if category is None:
        return None
    return CATEGORY_DEFAULT_TIER_RANK.get(category)


# ─── Fuzzy match (B1a) ─────────────────────────────────────────────────────────

class ProductMatchCandidate(BaseModel):
    """One match returned for a query — Product id + name + similarity score 0..100."""
    product_id: UUID
    name:       str
    score:      int = Field(..., ge=0, le=100)


class ProductMatchResult(BaseModel):
    """All matches found for a single query string."""
    query:   str
    matches: list[ProductMatchCandidate]


class ProductMatchBatchRequest(BaseModel):
    """Batch a list of queries (typically one per invoice line item).

    `threshold` is the minimum score below which a candidate is dropped.
    `top_k` caps results per query so the response stays bounded.
    """
    queries:   list[str] = Field(..., min_length=1, max_length=200)
    threshold: int       = Field(default=70, ge=0, le=100)
    top_k:     int       = Field(default=3,  ge=1, le=10)


class ProductMatchBatchResponse(BaseModel):
    """One result per query, same order as input."""
    results: list[ProductMatchResult]

