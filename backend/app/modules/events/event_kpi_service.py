"""Event-level KPI aggregator for the redesigned dashboard top strip.

Sibling of category_totals_service (which is PER-BAR for the bar cards).
This one rolls revenue up to the EVENT level and shapes it for the
headline KPIs:

  - Drinks: units + revenue (100% Omar), broken into 4 families
    (cocktails / beer / wine / soft) + an "other" catch-all.
  - Food: units + GROSS revenue, broken by FoodType, with the event's
    revenue-share % applied once to yield Omar's NET cut (net_revenue_eur,
    a side figure — see below).
  - Total Revenue = GROSS drinks + food revenue (drink_rev + food_gross),
    NOT net of the food-vendor split. This was previously undocumented
    drift from this file's own docstring, which claimed NET — fixed
    2026-08 alongside F-01. Owner net take-home (after deposits
    returned, VAT, and the food-vendor share) is a separate, clearly
    labelled figure in the Revenue Breakdown modal
    (RevenueBreakdownService.OwnerWaterfall.net_takehome_eur) — this
    endpoint does not attempt to reproduce it.
  - unmapped_revenue_eur: confirmed EventOrder revenue whose POS shop
    has not yet been mapped to a Bar (bar_id IS NULL). Until 2026-08
    this was silently dropped from total_revenue_eur entirely (an
    inner join to Bar excluded it) — that was the original bug.
    total_revenue_eur now includes it; this field surfaces the amount
    explicitly rather than leaving it invisible. It is NOT included in
    drinks.revenue_eur or food.gross_revenue_eur, since attributing it
    to drinks vs. food requires knowing which bar it belongs to.

Units + the drinks/food-family breakdown still come from
StockTransaction (SUM(qty * price_cents) / 100 over rows whose source
is in REVENUE_SOURCES and price_cents IS NOT NULL) — unchanged. The
euro totals come from EventOrder.fiscal_gross_cents (see fiscal_stmt
below) — the money-of-record from Slesh, correct for food-truck sales
and no-recipe drinks that StockTransaction misses.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.event_kpi_schemas import (
    DrinkCategoryLine,
    DrinksSummary,
    EventKpiSummary,
    FoodSummary,
    FoodTypeLine,
)
from app.modules.bars.models import Bar
from app.modules.events.models import Event, EventOrder
from app.modules.predictions.predictors.heuristic import (
    REVENUE_SOURCES,
    _classify_category,
)
from app.modules.products.models import Product, ProductCategory
from app.modules.stock_transactions.models import StockTransaction

_CENTS = Decimal("100")
_PENNY = Decimal("0.01")


def _money(d: Decimal) -> Decimal:
    """Quantize to 2dp (euros), round half-up."""
    return d.quantize(_PENNY, rounding=ROUND_HALF_UP)


def _enum_value(x: object) -> object:
    """Return .value for an enum member, or x unchanged if it's already a
    plain string/None. Guards against native-enum vs string drift."""
    return getattr(x, "value", x)


# Granular drink category (DB enum value OR _classify_category fallback)
# -> one of the 4 display families. Anything absent -> "other".
_DRINK_FAMILY: dict[str, str] = {
    ProductCategory.BEER_DRAFT.value:       "beer",
    ProductCategory.BEER_BOTTLE.value:      "beer",
    ProductCategory.BASIC_COCKTAIL.value:   "cocktails",
    ProductCategory.PREMIUM_COCKTAIL.value: "cocktails",
    ProductCategory.WINE_RED.value:         "wine",
    ProductCategory.WINE_WHITE.value:       "wine",
    ProductCategory.WINE_SPARKLING.value:   "wine",
    ProductCategory.SOFT_DRINK.value:       "soft",
    # name-fallback buckets from _classify_category()
    "beer":              "beer",
    "wine":              "wine",
    "cocktails":         "cocktails",
    "premium_cocktails": "cocktails",
    "soft_drink":        "soft",
    "soft":              "soft",
}


def _drink_family(category_value: str | None, product_name: str) -> str:
    granular = category_value if category_value else _classify_category(product_name)
    return _DRINK_FAMILY.get(granular, "other")


class EventKpiSummaryService:
    """Aggregates one event's revenue-producing transactions into KPIs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> EventKpiSummary | None:
        """Return the event KPI summary, or None if the event is not found
        for this tenant. An existing event with no revenue rows yet returns
        a zeroed summary (units=0, revenue=0, empty breakdowns)."""
        # 1. Verify event belongs to tenant + read the food share.
        row = (await self.db.execute(
            select(Event.id, Event.food_revenue_share_pct).where(
                Event.id == event_id, Event.tenant_id == tenant_id,
            )
        )).first()
        if row is None:
            return None
        share_pct = (
            100 if row.food_revenue_share_pct is None
            else int(row.food_revenue_share_pct)
        )

        # 2. One revenue-producing row per (product_type, category, food_type,
        #    name), event + tenant scoped.
        revenue_expr = (
            func.sum(StockTransaction.qty * StockTransaction.price_cents) / _CENTS
        ).label("revenue_eur")
        units_expr = func.sum(StockTransaction.qty).label("units")

        stmt = (
            select(
                Product.product_type.label("product_type"),
                Product.category.label("category"),
                Product.food_type.label("food_type"),
                Product.name.label("product_name"),
                units_expr,
                revenue_expr,
            )
            .select_from(StockTransaction)
            .join(Product, Product.id == StockTransaction.product_id)
            .where(
                StockTransaction.tenant_id == tenant_id,
                StockTransaction.event_id == event_id,
                StockTransaction.source.in_(REVENUE_SOURCES),
                StockTransaction.price_cents.is_not(None),
                StockTransaction.pos_line_status == "confirmed",
            )
            .group_by(
                Product.product_type, Product.category,
                Product.food_type, Product.name,
            )
        )
        rows = (await self.db.execute(stmt)).all()

        # 2b. Fiscal totals from event_orders (2026-07-05, corrected 2026-08
        # for F-01: refund exclusion + unmapped-order visibility).
        # WHY event_orders, not stock_transactions: stock_transactions only
        # reflects drinks WITH recipes at recipe-enabled bars — it MISSES
        # food-truck sales and drinks like acqua/bicchiere that have no
        # recipe. event_orders is the money-of-record from Slesh (every
        # wristband tap). Depletion tracking (stock section, alerts) still
        # uses stock_transactions — unchanged.
        #
        # confirmed_line_count > 0 excludes fully-refunded orders — the
        # same filter RevenueBreakdownService already applies (see
        # docs/revenue-calculation-bible.md). Previously absent here, which
        # meant a refunded order's fiscal amount stayed counted on this
        # tile after the Breakdown modal had already excluded it.
        #
        # Two queries:
        #  - unsplit: the TRUE event total, every confirmed order,
        #    regardless of whether its shop has been mapped to a bar yet.
        #    This is what total_revenue_eur is built from.
        #  - fiscal_stmt: the same confirmed orders, but inner-joined to
        #    Bar and grouped by bar_type so the drinks/food split (needed
        #    for the food-vendor share) can be computed. This join
        #    structurally cannot include bar_id IS NULL orders — there is
        #    no bar_type to attribute them to — so it stays scoped to
        #    drinks/food only, same as before.
        #  - unmapped: confirmed orders with bar_id IS NULL specifically,
        #    queried directly (not derived by subtraction, so it can never
        #    disagree with reality due to rounding or an unrelated
        #    bar_type like "mixed"/"merch"/"service" that isn't drinks or
        #    food either).
        confirmed_filter = (
            EventOrder.tenant_id == tenant_id,
            EventOrder.event_id == event_id,
            EventOrder.confirmed_line_count > 0,
        )

        unsplit_stmt = (
            select(func.sum(EventOrder.fiscal_gross_cents).label("gross_cents"))
            .select_from(EventOrder)
            .where(*confirmed_filter)
        )
        unsplit_total_cents = (await self.db.execute(unsplit_stmt)).scalar() or 0

        fiscal_stmt = (
            select(
                Bar.bar_type.label("bar_type"),
                func.sum(EventOrder.fiscal_gross_cents).label("gross_cents"),
            )
            .select_from(EventOrder)
            .join(Bar, Bar.id == EventOrder.bar_id)
            .where(*confirmed_filter)
            .group_by(Bar.bar_type)
        )
        fiscal_rows = (await self.db.execute(fiscal_stmt)).all()
        fiscal_drinks_cents = 0
        fiscal_food_gross_cents = 0
        for fr in fiscal_rows:
            gross_cents = fr.gross_cents or 0
            btype_val = getattr(fr.bar_type, "value", fr.bar_type)
            if btype_val == "drinks":
                fiscal_drinks_cents = gross_cents
            elif btype_val == "food":
                fiscal_food_gross_cents = gross_cents
        fiscal_drinks_eur = _money(Decimal(fiscal_drinks_cents) / _CENTS)
        fiscal_food_gross_eur = _money(Decimal(fiscal_food_gross_cents) / _CENTS)

        unmapped_stmt = (
            select(func.sum(EventOrder.fiscal_gross_cents).label("gross_cents"))
            .select_from(EventOrder)
            .where(*confirmed_filter, EventOrder.bar_id.is_(None))
        )
        unmapped_cents = (await self.db.execute(unmapped_stmt)).scalar() or 0
        unmapped_revenue_eur = _money(Decimal(unmapped_cents) / _CENTS)

        # 3. Roll up.
        drink_units = 0
        drink_rev = Decimal(0)
        food_units = 0
        food_gross = Decimal(0)
        by_family: dict[str, dict] = defaultdict(
            lambda: {"units": 0, "revenue": Decimal(0)}
        )
        by_ftype: dict[str, dict] = defaultdict(
            lambda: {"units": 0, "revenue": Decimal(0)}
        )

        for r in rows:
            units = int(r.units or 0)
            revenue = Decimal(str(r.revenue_eur or 0))
            ptype = _enum_value(r.product_type) if r.product_type is not None else None

            if ptype == "drink":
                cat_value = _enum_value(r.category) if r.category is not None else None
                family = _drink_family(cat_value, r.product_name or "")
                drink_units += units
                drink_rev += revenue
                by_family[family]["units"] += units
                by_family[family]["revenue"] += revenue
            elif ptype == "food":
                ftype = _enum_value(r.food_type) if r.food_type is not None else "other"
                food_units += units
                food_gross += revenue
                by_ftype[ftype]["units"] += units
                by_ftype[ftype]["revenue"] += revenue
            # ingredient / supply: not part of the guest-facing KPI (the
            # locked formula is drinks + food only). Intentionally skipped.

        # 4. Apply the partnership split to food.
        # Header total = GROSS revenue (what customers paid at the bars),
        # INCLUDING orders not yet mapped to a bar (F-01) — see
        # unmapped_revenue_eur. This matches Slesh's dashboard exactly.
        # Net take-home after the food-truck split is exposed separately
        # via food.net_revenue_eur (and, more completely, via
        # RevenueBreakdownService.OwnerWaterfall.net_takehome_eur).
        # SWAPPED to fiscal source (2026-07-05); refund + unmapped
        # handling corrected (F-01, 2026-08).
        food_gross = fiscal_food_gross_eur
        food_net = _money(food_gross * Decimal(share_pct) / Decimal(100))
        drink_rev = fiscal_drinks_eur
        total = _money(Decimal(unsplit_total_cents) / _CENTS)

        drink_lines = [
            DrinkCategoryLine(family=f, units=v["units"], revenue_eur=_money(v["revenue"]))
            for f, v in by_family.items()
        ]
        drink_lines.sort(key=lambda c: -c.units)

        food_lines = [
            FoodTypeLine(food_type=t, units=v["units"], revenue_eur=_money(v["revenue"]))
            for t, v in by_ftype.items()
        ]
        food_lines.sort(key=lambda c: -c.units)

        return EventKpiSummary(
            event_id=event_id,
            total_revenue_eur=total,
            unmapped_revenue_eur=unmapped_revenue_eur,
            drinks=DrinksSummary(
                units=drink_units,
                revenue_eur=drink_rev,
                by_category=drink_lines,
            ),
            food=FoodSummary(
                units=food_units,
                gross_revenue_eur=food_gross,
                share_pct=share_pct,
                net_revenue_eur=food_net,
                by_type=food_lines,
            ),
        )
