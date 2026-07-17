"""SQLAlchemy models for the event_storage module.

Two tables:
- supplier_products: master list of items available from suppliers
  (e.g. Partesa). Reusable across events. Seeded from the supplier's
  first invoice; new items added via wizard "+ Add new" on demand.
- event_stock_items: per-event purchase rows. One row per
  (event, supplier_product) declaring "we bought this many of these
  for this event". Feeds the warehouse + inventory pages.

The wizard's step 7 ("Storage") writes both tables: any unknown item
gets auto-created in supplier_products before the event_stock_items
row is upserted.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel


class SupplierProduct(TenantScopedModel):
    """Master-list item. One row per distinct SKU from a supplier."""

    __tablename__ = "supplier_products"

    # Supplier identification. Flat string for now (Partesa is the only
    # supplier at Sundance 1). Becomes FK to a suppliers table later.
    supplier_name: Mapped[str] = mapped_column(
        String(128), nullable=False, default="Partesa",
    )

    # Supplier's stable internal code (Partesa "cod. articolo"), e.g.
    # "2193T" for Beefeater. The identity field — unique per tenant.
    supplier_sku: Mapped[str] = mapped_column(String(64), nullable=False)

    # Full descriptive name as it appears on the invoice.
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Coarse category for the wizard's accordion grouping + dropdown
    # filter. Values: gin, vodka, whiskey, rum, tequila, mezcal,
    # aperitivo, beer_keg, sparkling, mixer, soft_drink, juice,
    # water_still, water_sparkling, equipment, premix, other.
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Default unit of measure (snapshot of supplier's invoice format):
    # BO=bottle, KAR=carton, FS=keg (fusto), BM=canister (bombola).
    default_unit: Mapped[str] = mapped_column(String(16), nullable=False)

    # How many drinkable units fit in one default_unit. 1 for BO,
    # 24/6/100 etc for KAR depending on inner pack size.
    units_per_pack: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )

    # Volume per single drinkable unit in ml (1000 for 1L, 750 for 75cl,
    # 30000 for a 30L keg). Optional — not all items have a meaningful
    # volume (e.g. CO2 canister).
    volume_per_unit_ml: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )

    # Most-recent supplier price (€/unit). Prefills the wizard quick-add
    # so Omar doesn't retype prices that rarely change.
    last_unit_price_eur: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "supplier_sku",
            name="uq_supplier_products_tenant_sku",
        ),
    )


class EventStockItem(TenantScopedModel):
    """Per-event purchase row. Declares how many of one supplier_product
    were bought for one event. Drives warehouse + inventory KPIs.
    """

    __tablename__ = "event_stock_items"

    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    supplier_product_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("supplier_products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Quantity received in default_unit terms (e.g. 240 bottles, 80
    # cartons, 15 kegs). Decimal to allow fractional intake edge cases.
    qty_received: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False,
    )

    # Snapshot of unit at entry time (in case supplier_product.default_unit
    # changes later — historical accuracy matters for forensics).
    unit: Mapped[str] = mapped_column(String(16), nullable=False)

    # Pricing — optional (Omar may declare qty only, defer pricing).
    unit_price_eur: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )
    discount_amount_eur: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )
    line_total_eur: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True,
    )
    vat_pct: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=22,
    )

    # Invoice provenance — used to group rows from the same purchase
    # and to display "received N items from invoice X" in the UI.
    invoice_number: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
    )
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "event_id", "supplier_product_id",
            name="uq_event_stock_items_tenant_event_sp",
        ),
    )


class EventStockBarAllocation(TenantScopedModel):
    """One dispatch event: Omar sends N of a supplier_product to a bar.

    History-preserving — every dispatch creates a NEW row (no unique
    constraint). Aggregations sum across rows. Returns/corrections are
    out of scope for Sundance 1; if needed later they can land as
    negative-qty rows or via a separate event_stock_bar_returns table.

    The activity feed on the Warehouse page IS this table sorted by
    created_at DESC, joined with supplier_products (item name) and
    bars (bar name) and users (who dispatched).
    """

    __tablename__ = "event_stock_bar_allocations"

    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    supplier_product_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("supplier_products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    bar_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("bars.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # How many of the supplier_product's default_unit were dispatched
    # (e.g. 100 BO of Beefeater, 5 KAR of Schweppes Tonica).
    qty_allocated: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False,
    )

    # Who did the dispatch. NULLable so user deletion doesn't wipe
    # historical allocations from the activity feed.
    dispatched_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)




class EventCategoryIngredient(TenantScopedModel):
    """Slesh-category → ingredient depletion rule for ml-based stock tracking.

    Each row declares: "When a sale of <slesh_category> rings up at
    <bar_id or any bar>, subtract <ml_per_sale> from <supplier_product>
    at the firing bar."

    Worst-case math design (locked with Hesam, June 13 2026):
    Multiple rows can share the same (event, slesh_category) so a single
    Signature sale depletes Vodka + Gin + Rum + Tequila in parallel.
    This systematically over-counts (the actual sale used just one
    spirit), firing ~Nx the alerts a perfectly-accurate system would.
    Omar accepts the noise; humans verify by physically walking past
    bottles when an alert fires. False positives << false negatives.

    bar_id semantics:
      NULL → rule applies to EVERY bar that sells this category
      set  → rule restricted to that specific bar (GIN No 3 sponsor at
             NO.3 BAR only — Premium category there depletes one extra
             bottle the other drink bars don't have)

    Thresholds drive auto-alert firing on status flips:
      healthy  (remaining_pct > 100 - threshold_pct_warn)
      low      (between warn and empty)
      critical (consumed >= threshold_pct_empty)
    """

    __tablename__ = "event_category_ingredients"

    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The exact category string Slesh sends in the order line (and which
    # we also set as Product.name for menu-button products). E.g.
    # "SPRITZ", "PREMIUM", "GIN TONIC", "HEINEKEN".
    slesh_category: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
    )

    # FK replacement for the free-text slesh_category join (migration aa5,
    # backfilled from slesh_category ↔ product.name matches). Nullable for
    # now — becomes NOT NULL in migration aa6 once prod backfill is done.
    # Root cause of the Sundance Jul-5 depletion outage: slesh_category and
    # product.name were two independently maintained string namespaces that
    # silently drifted apart, zeroing out consumed_ml for hours.
    product_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    supplier_product_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("supplier_products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    ml_per_sale: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False,
    )

    bar_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("bars.id", ondelete="CASCADE"),
        nullable=True,
    )

    threshold_pct_warn: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("70.00"),
    )
    threshold_pct_empty: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("100.00"),
    )

    # false = required alcohol base (Catalog page's "Alcohol base"
    # section); true = optional mixer/extra ("Mixers & extras" section).
    # The alerts/depletion engine treats both identically — this flag
    # is FE display grouping only (Chunk 2, Sundance 15 recipe editor).
    is_optional: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
