"""SQLAlchemy ORM model for the products module.

A Product is anything trackable in the catalog — drinks, food, ingredients,
or supplies. Drinks additionally carry a category and tier_rank for
analytics/ML purposes (anomaly detection across quality tiers).

Design rationale:
- Unified table with product_type enum (per Q1 of tonight's session)
- Native Postgres enums for type safety (per Q4 of tonight's session)
- Soft-delete via is_archived preserves FK chains from future events,
  recipes, and stock allocations (hard delete would break historical data)
"""
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    Index,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel


# ─── Enums (match the Postgres types created in migration b1) ─────────────────

class ProductType(str, PyEnum):
    """What KIND of thing this product is. Polymorphic discriminator."""
    DRINK = "drink"
    FOOD = "food"
    INGREDIENT = "ingredient"   # e.g. rum bottle, lime, sugar (recipe inputs)
    SUPPLY = "supply"           # e.g. cups, ice, straws


class ProductCategory(str, PyEnum):
    """Taxonomy for DRINK products — confirmed by Omar (email April 2026).

    Only populated when product_type = DRINK. Food/ingredient/supply leave
    category NULL. The category drives the default tier_rank derivation.
    """
    BEER_DRAFT       = "beer_draft"         # Italian: alla spina
    BEER_BOTTLE      = "beer_bottle"        # Italian: in bottiglia
    BASIC_COCKTAIL   = "basic_cocktail"
    PREMIUM_COCKTAIL = "premium_cocktail"
    WINE_RED         = "wine_red"           # Italian: rosso
    WINE_WHITE       = "wine_white"         # Italian: bianco
    WINE_SPARKLING   = "wine_sparkling"     # Italian: frizzante
    SOFT_DRINK       = "soft_drink"         # Italian: analcolici


class ProductUnit(str, PyEnum):
    """Unit of measure. Drives how quantity is interpreted downstream
    in recipes, stock ledgers, and transaction data from Slesh POS.
    """
    BOTTLE      = "bottle"       # full bottle (e.g. 750ml wine, 1L spirit)
    GLASS       = "glass"        # poured glass
    CAN         = "can"          # aluminum can (beer, soft drink)
    DRAFT_GLASS = "draft_glass"  # poured from tap
    SHOT        = "shot"         # 25-40ml pour
    PIECE       = "piece"        # countable item (food plate, straw)
    GRAM        = "gram"         # weight-based ingredient
    ML          = "ml"           # volume-based ingredient


# ─── Tier rank derivation (drinks only) ───────────────────────────────────────
# When product_type=DRINK and tier_rank is not explicitly provided, the service
# layer derives it from category using this map. Callers may override by
# passing an explicit tier_rank (e.g., a rare Barolo in WINE_RED → tier 4).

CATEGORY_DEFAULT_TIER_RANK: dict[ProductCategory, int] = {
    ProductCategory.BEER_DRAFT:       1,
    ProductCategory.SOFT_DRINK:       1,
    ProductCategory.BEER_BOTTLE:      2,
    ProductCategory.BASIC_COCKTAIL:   2,
    ProductCategory.WINE_RED:         2,
    ProductCategory.WINE_WHITE:       2,
    ProductCategory.PREMIUM_COCKTAIL: 3,
    ProductCategory.WINE_SPARKLING:   3,
}


# ─── Model ────────────────────────────────────────────────────────────────────

class Product(TenantScopedModel):
    """A catalog product — reusable across events.

    Examples:
        - name="House Mojito"   product_type=DRINK  category=BASIC_COCKTAIL  tier=2
        - name="Barolo 2020"    product_type=DRINK  category=WINE_RED        tier=4 (override)
        - name="Bacardi Rum 1L" product_type=INGREDIENT  category=None       unit=BOTTLE
        - name="Plastic Cup"    product_type=SUPPLY      category=None       unit=PIECE
    """
    __tablename__ = "products"

    # Enforce CHECK constraints + index names matching migration b1
    __table_args__ = (
        CheckConstraint(
            "tier_rank IS NULL OR (tier_rank >= 1 AND tier_rank <= 4)",
            name="products_tier_rank_range",
        ),
        CheckConstraint(
            "default_price_cents IS NULL OR default_price_cents >= 0",
            name="products_price_nonneg",
        ),
        # Mirror the partial unique index (alembic already created it at DB level;
        # this is for SQLAlchemy metadata awareness, no schema impact)
        Index(
            "uq_products_tenant_name_type_active",
            "tenant_id", "name", "product_type",
            unique=True,
            postgresql_where=text("is_archived = false"),
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    product_type: Mapped[ProductType] = mapped_column(
        Enum(
            ProductType,
            name="product_type",
            values_callable=lambda enum: [e.value for e in enum],
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
        index=True,
    )

    category: Mapped[ProductCategory | None] = mapped_column(
        Enum(
            ProductCategory,
            name="product_category",
            values_callable=lambda enum: [e.value for e in enum],
            native_enum=True,
            create_type=False,
        ),
        nullable=True,
        index=True,
    )

    tier_rank: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    unit: Mapped[ProductUnit] = mapped_column(
        Enum(
            ProductUnit,
            name="product_unit",
            values_callable=lambda enum: [e.value for e in enum],
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )

    default_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Slesh product._id — populated by reference data sync (B5).
    # Indexed because every order-line ingest looks up product by this.
    external_pos_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
    )

    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        index=True,
    )
