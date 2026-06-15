"""Event-level KPI aggregator for the redesigned dashboard top strip.

Sibling of category_totals_service (which is PER-BAR for the bar cards).
This one rolls the SAME revenue-producing StockTransaction rows up to the
EVENT level and shapes them for the headline KPIs:

  - Drinks: units + revenue (100% Omar), broken into 4 families
    (cocktails / beer / wine / soft) + an "other" catch-all.
  - Food: units + GROSS revenue, broken by FoodType, with the event's
    revenue-share % applied once to yield Omar's NET cut.
  - Total Revenue = drinks revenue + food NET = Omar's take.

Single source of truth for revenue (shared with category_totals_service
and reports/aggregator): SUM(qty * price_cents) / 100 over rows whose
source is in REVENUE_SOURCES and price_cents IS NOT NULL.
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
from app.modules.events.models import Event
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

        # 4. Apply the partnership split to food, then total.
        food_gross = _money(food_gross)
        food_net = _money(food_gross * Decimal(share_pct) / Decimal(100))
        drink_rev = _money(drink_rev)
        total = _money(drink_rev + food_net)

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
