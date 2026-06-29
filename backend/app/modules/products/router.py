"""HTTP router for the products module.

Contract reference: §1.1 (thin router) + §7.3 (typed error envelope).

Endpoints:
    GET    /products                         list (filters: type, category, include_archived)
    GET    /products/{id}                    single product (includes archived)
    POST   /products                         create (service auto-derives tier_rank for drinks)
    PATCH  /products/{id}                    partial update (product_type + is_archived NOT patchable)
    POST   /products/{id}/archive            soft-delete (sets is_archived=true)
    POST   /products/{id}/restore            un-archive (blocks on name+type collision)

Note: no DELETE endpoint. Products are long-lived catalog entries referenced
by future event menus, recipes, and stock allocations. Use archive instead.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.products.models import ProductCategory, ProductType
from app.modules.products.matcher import fuzzy_match_products
from app.modules.products.schemas import (
    ProductCreate,
    ProductMatchBatchRequest,
    ProductMatchBatchResponse,
    ProductMatchCandidate,
    ProductMatchResult,
    ProductResponse,
    ProductUpdate,
)
from app.modules.products.service import (
    DuplicateProductError,
    InvalidProductShapeError,
    ProductAlreadyArchivedError,
    ProductNotArchivedError,
    ProductNotFoundError,
    ProductService,
)


async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return current_user.tenant_id


router = APIRouter()


# ─── Read endpoints ───────────────────────────────────────────────────────────

@router.get("", response_model=list[ProductResponse])
async def list_products(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    product_type: Annotated[ProductType | None, Query(description="Filter by type")] = None,
    category: Annotated[ProductCategory | None, Query(description="Filter by category (drinks only)")] = None,
    include_archived: Annotated[bool, Query(description="Include archived products")] = False,
) -> list[ProductResponse]:
    """List catalog products for the current tenant.

    Common use cases:
    - Menu builder UI: list(product_type=DRINK) — only active drinks
    - Admin catalog view: list(include_archived=True)
    - Category browser: list(product_type=DRINK, category=WINE_RED)
    """
    service = ProductService(db)
    products = await service.list_products(
        tenant_id,
        product_type=product_type,
        category=category,
        include_archived=include_archived,
    )
    return [ProductResponse.model_validate(p) for p in products]


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> ProductResponse:
    """Fetch a single product (active or archived)."""
    service = ProductService(db)
    try:
        product = await service.get_product(tenant_id, product_id)
    except ProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "product_not_found", "message": str(e)},
        )
    return ProductResponse.model_validate(product)


# ─── Write endpoints ──────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_product(
    payload: ProductCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> ProductResponse:
    """Create a new catalog product.

    Error responses:
    - 422 invalid_shape        — drink missing category, or non-drink has category/tier_rank
    - 409 duplicate_product    — active product with same name+type exists
    """
    service = ProductService(db)
    try:
        product = await service.create_product(tenant_id, payload)
    except InvalidProductShapeError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_shape",
                "message": str(e),
                "field": e.field,
            },
        )
    except DuplicateProductError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_product",
                "message": str(e),
                "existing_id": str(e.existing.id),
            },
        )
    return ProductResponse.model_validate(product)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> ProductResponse:
    """Partial update.

    Not patchable via this endpoint:
    - product_type (changing type retroactively invalidates downstream refs)
    - is_archived (use /archive and /restore for explicit state changes)
    """
    service = ProductService(db)
    try:
        product = await service.update_product(tenant_id, product_id, payload)
    except ProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "product_not_found", "message": str(e)},
        )
    except InvalidProductShapeError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_shape",
                "message": str(e),
                "field": e.field,
            },
        )
    except DuplicateProductError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_product",
                "message": str(e),
                "existing_id": str(e.existing.id),
            },
        )
    return ProductResponse.model_validate(product)


# ─── Archive / Restore ────────────────────────────────────────────────────────

@router.post("/{product_id}/archive", response_model=ProductResponse)
async def archive_product(
    product_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> ProductResponse:
    """Soft-delete by setting is_archived=true. 409 if already archived."""
    service = ProductService(db)
    try:
        product = await service.archive_product(tenant_id, product_id)
    except ProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "product_not_found", "message": str(e)},
        )
    except ProductAlreadyArchivedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "already_archived", "message": str(e)},
        )
    return ProductResponse.model_validate(product)


@router.post("/{product_id}/restore", response_model=ProductResponse)
async def restore_product(
    product_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> ProductResponse:
    """Un-archive. Blocks if an active product with the same name+type
    exists (would collide with the partial unique index)."""
    service = ProductService(db)
    try:
        product = await service.restore_product(tenant_id, product_id)
    except ProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "product_not_found", "message": str(e)},
        )
    except ProductNotArchivedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "not_archived", "message": str(e)},
        )
    except DuplicateProductError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_product",
                "message": str(e),
                "existing_id": str(e.existing.id),
            },
        )
    return ProductResponse.model_validate(product)


# ─── Fuzzy match (B1a) ────────────────────────────────────────────────────────

@router.post(
    "/match-batch",
    response_model=ProductMatchBatchResponse,
    summary="Fuzzy-match a batch of descriptions against existing products",
)
async def match_products_batch(
    body: ProductMatchBatchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> ProductMatchBatchResponse:
    """For each query string in `body.queries`, return up to `top_k`
    Catalog products that look similar.

    Used primarily by the invoice-upload modal: parse a PDF, then call
    this with all line-item descriptions in one batch to surface match
    suggestions inline in the preview table.

    The candidate pool is the tenant\'s ACTIVE products (archived
    excluded — Omar shouldn\'t be matching new invoices against products
    he\'s already retired).
    """
    service = ProductService(db)
    products = await service.list_products(tenant_id, include_archived=False)

    results: list[ProductMatchResult] = []
    for q in body.queries:
        candidates = fuzzy_match_products(
            q, products, threshold=body.threshold, top_k=body.top_k,
        )
        results.append(ProductMatchResult(
            query=q,
            matches=[
                ProductMatchCandidate(
                    product_id=c.product.id, name=c.product.name, score=c.score,
                )
                for c in candidates
            ],
        ))
    return ProductMatchBatchResponse(results=results)

