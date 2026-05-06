"""SQLAlchemy ORM models for the system-wide recipe template catalog.

These models are TENANT-FREE (catalog is universal — see migration
o3_add_recipe_templates). Per-tenant recipe definitions live in the
existing `recipes` table.

Read-mostly: rows are written exactly twice — once at initial seed,
re-upserted by slug whenever scripts/seed_recipe_templates.py runs.
There is no API mutation path for these tables.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RecipeTemplate(Base):
    """A canonical IBA-curated cocktail recipe."""

    __tablename__ = "recipe_templates"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_recipe_templates_slug"),
    )

    id:   Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str]  = mapped_column(String(64), nullable=False)

    name:        Mapped[str]        = mapped_column(String(128), nullable=False)
    category:    Mapped[str]        = mapped_column(String(32),  nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text,        nullable=True)
    glass_type:  Mapped[str | None] = mapped_column(String(32),  nullable=True)
    total_ml:    Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    items: Mapped[list["RecipeTemplateItem"]] = relationship(
        "RecipeTemplateItem",
        back_populates="template",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RecipeTemplateItem.order_index",
    )


class RecipeTemplateItem(Base):
    """One ingredient line in a template — by logical role, not Product UUID."""

    __tablename__ = "recipe_template_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="recipe_template_items_qty_positive"),
        UniqueConstraint(
            "template_id", "ingredient_role",
            name="uq_recipe_template_items_role",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    template_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("recipe_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ingredient_role:  Mapped[str] = mapped_column(String(64),  nullable=False)
    ingredient_label: Mapped[str] = mapped_column(String(128), nullable=False)
    qty:              Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    unit:             Mapped[str] = mapped_column(String(32),  nullable=False)
    order_index:      Mapped[int] = mapped_column(Integer,     nullable=False, default=0)

    template: Mapped[RecipeTemplate] = relationship(
        "RecipeTemplate", back_populates="items",
    )


__all__ = ["RecipeTemplate", "RecipeTemplateItem"]
