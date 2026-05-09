"""Database queries for the products module — pure data access.

Contract reference: §1.1 (4-layer architecture).

Design notes:
- Archive is a soft-delete (sets is_archived=true). No hard delete method
  exposed at this layer because Products are referenced by future
  event menus, recipes, and stock allocations.
- find_by_name_type_active is used by the service layer BEFORE creating
  a product, to give a friendly 409 duplicate_product error instead of
  letting the partial unique index raise a raw IntegrityError.
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.products.models import (
    Product,
    ProductCategory,
    ProductType,
)
from app.modules.products.schemas import ProductCreate, ProductUpdate


class ProductRepository:
    """Handles all SQL operations for Product records."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Read ─────────────────────────────────────────────────────────────────

    async def list_for_tenant(
        self,
        tenant_id: UUID,
        *,
        product_type: ProductType | None = None,
        category: ProductCategory | None = None,
        include_archived: bool = False,
    ) -> Sequence[Product]:
        """List products for a tenant, optionally filtered.

        Default behavior hides archived products (the common case for
        menu-building UIs). Pass include_archived=True for admin views.
        """
        stmt = (
            select(Product)
            .where(Product.tenant_id == tenant_id)
            .order_by(Product.name.asc())
        )
        if product_type is not None:
            stmt = stmt.where(Product.product_type == product_type)
        if category is not None:
            stmt = stmt.where(Product.category == category)
        if not include_archived:
            stmt = stmt.where(Product.is_archived.is_(False))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_id(
        self,
        tenant_id: UUID,
        product_id: UUID,
    ) -> Product | None:
        """Fetch a single product, scoped to tenant. Includes archived."""
        stmt = (
            select(Product)
            .where(Product.id == product_id)
            .where(Product.tenant_id == tenant_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def find_active_by_name_type(
        self,
        tenant_id: UUID,
        name: str,
        product_type: ProductType,
    ) -> Product | None:
        """Lookup used by service layer for dedup checks before create.

        Returns the existing ACTIVE (is_archived=false) product with the
        same name+type if one exists, else None. Case-insensitive match
        on name to catch 'House Mojito' vs 'house mojito'.
        """
        stmt = (
            select(Product)
            .where(Product.tenant_id == tenant_id)
            .where(Product.name.ilike(name))
            .where(Product.product_type == product_type)
            .where(Product.is_archived.is_(False))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ─── Write (service commits, repo flushes) ────────────────────────────────

    async def create(
        self,
        tenant_id: UUID,
        data: ProductCreate,
        resolved_tier_rank: int | None,
    ) -> Product:
        """Insert a new product. Service computes resolved_tier_rank first."""
        product = Product(
            tenant_id=tenant_id,
            name=data.name,
            product_type=data.product_type,
            category=data.category,
            tier_rank=resolved_tier_rank,
            unit=data.unit,
            default_price_cents=data.default_price_cents,
            external_pos_id=data.external_pos_id,
            barcode=data.barcode,
            is_archived=False,
        )
        self.db.add(product)
        await self.db.flush()
        await self.db.refresh(product)
        return product

    async def update(
        self,
        product: Product,
        data: ProductUpdate,
        resolved_tier_rank: int | None | type[Ellipsis] = ...,
    ) -> Product:
        """Apply a partial update.

        resolved_tier_rank semantics:
        - Ellipsis (default) → do not touch tier_rank column
        - None               → set tier_rank = NULL
        - int                → set tier_rank = that integer
        This three-way flag is needed because PATCH semantics distinguish
        'absent from payload' (don't touch) vs 'explicitly null' (clear).
        """
        payload = data.model_dump(exclude_unset=True)
        # tier_rank is handled via the explicit resolved parameter to
        # preserve the three-way distinction. Pop it from the auto-loop.
        payload.pop("tier_rank", None)
        for field, value in payload.items():
            setattr(product, field, value)
        if resolved_tier_rank is not Ellipsis:
            product.tier_rank = resolved_tier_rank
        self.db.add(product)
        await self.db.flush()
        await self.db.refresh(product)
        return product

    async def set_archived(self, product: Product, archived: bool) -> Product:
        """Flip the is_archived flag. Used by archive and restore endpoints."""
        product.is_archived = archived
        self.db.add(product)
        await self.db.flush()
        await self.db.refresh(product)
        return product
