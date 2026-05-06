"""SQLAlchemy ORM models for the recipes module.

Relationships:
    Recipe.items           : list[RecipeItem]   (one-to-many, cascade delete)
    RecipeItem.recipe      : Recipe             (many-to-one back-ref)

The CASCADE is enforced both at the DB layer (FK ON DELETE CASCADE in
migration e1) and at the ORM layer (cascade='all, delete-orphan') so
that deleting a recipe via SQLAlchemy properly triggers cleanup even
when SQLAlchemy does the delete in-memory.
"""
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.tenancy import TenantScopedModel
from app.modules.products.models import ProductUnit


# ─── Recipe header ────────────────────────────────────────────────────────────

class Recipe(TenantScopedModel):
    """Recipe header — one per drink Product within a tenant."""
    __tablename__ = "recipes"

    __table_args__ = (
        CheckConstraint("yield_qty > 0", name="recipes_yield_positive"),
        Index(
            "uq_recipes_tenant_drink",
            "tenant_id", "drink_product_id",
            unique=True,
        ),
    )

    drink_product_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    yield_qty: Mapped[Decimal] = mapped_column(
        Numeric(10, 3),
        nullable=False,
        server_default=text("1"),
    )

    yield_unit: Mapped[ProductUnit] = mapped_column(
        PgEnum(
            ProductUnit,
            name="product_unit",
            values_callable=lambda enum: [e.value for e in enum],
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ─── Phase F.8e additions ──────────────────────────────────────────
    # display_name lets the Owner give a friendly label to their recipe
    # (e.g. "Sundance Long Island" for the "Cocktail" Slesh product).
    # NULL falls back to the drink Product\'s name in UIs.
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # template_id is OPTIONAL — set when a recipe was built from an IBA
    # template (for traceability + "based on Long Island Iced Tea" badge).
    # FK ON DELETE SET NULL: deleting a template never destroys tenant recipes.
    template_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("recipe_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ORM relationship — cascades deletes through the ORM for safety
    items: Mapped[list["RecipeItem"]] = relationship(
        "RecipeItem",
        back_populates="recipe",
        cascade="all, delete-orphan",
        lazy="selectin",   # eager-load items whenever a Recipe is fetched
        order_by="RecipeItem.created_at.asc()",
    )


# ─── Recipe item (ingredient line) ────────────────────────────────────────────

class RecipeItem(TenantScopedModel):
    """One ingredient line within a Recipe."""
    __tablename__ = "recipe_items"

    __table_args__ = (
        CheckConstraint("qty > 0", name="recipe_items_qty_positive"),
        Index(
            "uq_recipe_items_recipe_ingredient",
            "recipe_id", "ingredient_product_id",
            unique=True,
        ),
    )

    recipe_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("recipes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ingredient_product_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    qty: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)

    unit: Mapped[ProductUnit] = mapped_column(
        PgEnum(
            ProductUnit,
            name="product_unit",
            values_callable=lambda enum: [e.value for e in enum],
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Back-reference
    recipe: Mapped[Recipe] = relationship(
        "Recipe",
        back_populates="items",
    )
