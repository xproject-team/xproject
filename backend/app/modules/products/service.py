"""Business logic for the products module.

Responsibilities beyond CRUD:
- Tier rank derivation for drinks (delegates to schemas.derive_tier_rank)
- Category coherence enforcement:
    product_type = DRINK     → category REQUIRED
    product_type != DRINK    → category MUST be NULL
    (same rule for tier_rank — only drinks carry it)
- Dedup check before create: returns a friendly 'duplicate_product' error
  instead of letting the partial unique index raise a raw IntegrityError
- Archive vs restore policy:
    - Archive: always allowed (soft-delete)
    - Restore: blocked if another active product with same name+type exists
      (would violate the partial unique index)

Contract reference: §1.5 (service commits, repo flushes).
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.products.models import (
    Product,
    ProductCategory,
    ProductType,
)
from app.modules.products.repository import ProductRepository
from app.modules.products.schemas import (
    ProductCreate,
    ProductUpdate,
    derive_tier_rank,
)


# ─── Domain exceptions (map to HTTP status codes in router) ───────────────────

class ProductNotFoundError(Exception):
    """Product does not exist OR belongs to another tenant. → 404."""


class DuplicateProductError(Exception):
    """A non-archived product with same (tenant, name, product_type) exists.
    → 409. Payload includes the existing product's id for client recovery.
    """
    def __init__(self, message: str, existing: Product) -> None:
        super().__init__(message)
        self.existing = existing


class InvalidProductShapeError(Exception):
    """Category coherence violation — drink missing category, or non-drink
    has category/tier_rank. → 422.
    """
    def __init__(self, message: str, field: str) -> None:
        super().__init__(message)
        self.field = field


class ProductAlreadyArchivedError(Exception):
    """Attempted to archive a product that is already archived. → 409 (idempotent-ish)."""


class ProductNotArchivedError(Exception):
    """Attempted to restore a product that is not archived. → 409."""


# ─── Coherence validator ─────────────────────────────────────────────────────

def _validate_shape(
    product_type: ProductType,
    category: ProductCategory | None,
    tier_rank: int | None,
) -> None:
    """Enforce 'only drinks carry category + tier_rank'."""
    if product_type is ProductType.DRINK:
        if category is None:
            raise InvalidProductShapeError(
                "category is required for drink products", field="category",
            )
    else:
        if category is not None:
            raise InvalidProductShapeError(
                f"{product_type.value} products must not have a category",
                field="category",
            )
        if tier_rank is not None:
            raise InvalidProductShapeError(
                f"{product_type.value} products must not have a tier_rank",
                field="tier_rank",
            )


# ─── Service ──────────────────────────────────────────────────────────────────

class ProductService:
    """All business logic for product operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ProductRepository(db)

    # ─── Read ─────────────────────────────────────────────────────────────────

    async def list_products(
        self,
        tenant_id: UUID,
        *,
        product_type: ProductType | None = None,
        category: ProductCategory | None = None,
        include_archived: bool = False,
    ) -> Sequence[Product]:
        return await self.repo.list_for_tenant(
            tenant_id,
            product_type=product_type,
            category=category,
            include_archived=include_archived,
        )

    async def get_product(self, tenant_id: UUID, product_id: UUID) -> Product:
        product = await self.repo.get_by_id(tenant_id, product_id)
        if product is None:
            raise ProductNotFoundError(f"Product {product_id} not found")
        return product

    # ─── Create ───────────────────────────────────────────────────────────────

    async def create_product(
        self,
        tenant_id: UUID,
        data: ProductCreate,
    ) -> Product:
        """Create a new product. Validates shape + dedup + derives tier_rank."""
        # 1. Coherence check (drink ↔ category rules)
        _validate_shape(data.product_type, data.category, data.tier_rank)

        # 2. Dedup check — friendly error before hitting partial unique index
        existing = await self.repo.find_active_by_name_type(
            tenant_id, data.name, data.product_type,
        )
        if existing is not None:
            raise DuplicateProductError(
                f"An active {data.product_type.value} named '{data.name}' "
                f"already exists in this catalog.",
                existing=existing,
            )

        # 3. Resolve tier_rank (auto-derive if not explicit, for drinks only)
        resolved_tier_rank = derive_tier_rank(
            data.product_type, data.category, data.tier_rank,
        )

        # 4. Persist
        product = await self.repo.create(tenant_id, data, resolved_tier_rank)
        await self.db.commit()
        return product

    # ─── Update ───────────────────────────────────────────────────────────────

    async def update_product(
        self,
        tenant_id: UUID,
        product_id: UUID,
        data: ProductUpdate,
    ) -> Product:
        """Partial update.

        Tier rank handling — three cases per PATCH semantics:
        1. Field absent from payload → don't touch (pass Ellipsis to repo)
        2. Field explicitly set to int → use it
        3. Field explicitly set to null BUT product is a drink with category
           → re-derive from category (user probably wants default)
        """
        product = await self.get_product(tenant_id, product_id)

        # Compute post-update state for coherence check
        new_name = data.name if data.name is not None else product.name
        new_category = data.category if "category" in data.model_fields_set else product.category
        # tier_rank three-way: fetch from payload.model_fields_set to detect
        # 'explicitly set' vs 'omitted'
        tier_rank_touched = "tier_rank" in data.model_fields_set
        new_tier_rank = data.tier_rank if tier_rank_touched else product.tier_rank

        _validate_shape(product.product_type, new_category, new_tier_rank)

        # Dedup check if name changed
        if data.name is not None and data.name.lower() != product.name.lower():
            existing = await self.repo.find_active_by_name_type(
                tenant_id, new_name, product.product_type,
            )
            if existing is not None and existing.id != product.id:
                raise DuplicateProductError(
                    f"Another active {product.product_type.value} named "
                    f"'{new_name}' already exists.",
                    existing=existing,
                )

        # Resolve tier_rank for repo call
        # - If the caller didn't touch tier_rank and also didn't change category,
        #   pass Ellipsis (no change).
        # - Otherwise compute the new resolved value.
        category_touched = "category" in data.model_fields_set
        if not tier_rank_touched and not category_touched:
            resolved_tier_rank: int | None | type[Ellipsis] = ...
        else:
            resolved_tier_rank = derive_tier_rank(
                product.product_type, new_category, new_tier_rank,
            )

        product = await self.repo.update(product, data, resolved_tier_rank)
        await self.db.commit()
        return product

    # ─── Archive / Restore ────────────────────────────────────────────────────

    async def archive_product(
        self,
        tenant_id: UUID,
        product_id: UUID,
    ) -> Product:
        product = await self.get_product(tenant_id, product_id)
        if product.is_archived:
            raise ProductAlreadyArchivedError(
                f"Product {product_id} is already archived"
            )
        product = await self.repo.set_archived(product, archived=True)
        await self.db.commit()
        return product

    async def restore_product(
        self,
        tenant_id: UUID,
        product_id: UUID,
    ) -> Product:
        product = await self.get_product(tenant_id, product_id)
        if not product.is_archived:
            raise ProductNotArchivedError(
                f"Product {product_id} is not archived"
            )
        # Prevent restore if it would collide with an active product
        existing = await self.repo.find_active_by_name_type(
            tenant_id, product.name, product.product_type,
        )
        if existing is not None:
            raise DuplicateProductError(
                f"Cannot restore: an active {product.product_type.value} named "
                f"'{product.name}' already exists. Archive or rename it first.",
                existing=existing,
            )
        product = await self.repo.set_archived(product, archived=False)
        await self.db.commit()
        return product
