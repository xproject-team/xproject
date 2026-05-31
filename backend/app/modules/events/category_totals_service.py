"""Per-bar, per-category sales aggregator for the dashboard.

Reads live StockTransaction rows for an event, classifies each line\'s
product into a display bucket via the hybrid resolver (Product.category
DB enum when set, _classify_category() name-fallback otherwise), and
returns:

  1. Bucket rollup per bar (4 drink buckets + food, for the bar cards)
  2. Top 5 drinks per bar by units, with granular category label
     (for Omar\'s "what\'s hot tonight" surface)

Single source of truth for what counts as revenue:
  REVENUE_SOURCES = ("slesh_pos", "manual_bartender")
  (imported from predictions/heuristic.py — same constant the ML and
  reports modules already use)

Revenue formula (mirrors reports/aggregator.py):
  SUM(qty * price_cents) / 100.0   →   euros

Spec: dashboard redesign LOCKED May 27 2026.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Iterable
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models import Bar
from app.modules.events.category_totals_schemas import (
    BarCategoryBucket,
    BarCategoryTotals,
    BarTopDrink,
    DisplayBucket,
    EventBarCategoryTotalsResponse,
)
from app.modules.events.models import Event
from app.modules.predictions.predictors.heuristic import (
    REVENUE_SOURCES,
    _classify_category,
)
from app.modules.products.models import Product, ProductCategory
from app.modules.stock_transactions.models import StockTransaction


# ─── Display rollup ──────────────────────────────────────────────────────
# Maps every granular category value (whether from Product.category enum
# or from _classify_category() name-fallback) to the 5 visible buckets.
# Categories NOT in this map are hidden from bar cards (mixers, supply,
# spirits) — they still count toward total_units / total_revenue.

_ROLLUP_TO_BUCKET: dict[str, DisplayBucket] = {
    # From Product.category enum (granular DB values)
    ProductCategory.BEER_DRAFT.value:       "beer",
    ProductCategory.BEER_BOTTLE.value:      "beer",
    ProductCategory.BASIC_COCKTAIL.value:   "cocktails",
    ProductCategory.PREMIUM_COCKTAIL.value: "premium_cocktails",
    ProductCategory.WINE_RED.value:         "wine",
    ProductCategory.WINE_WHITE.value:       "wine",
    ProductCategory.WINE_SPARKLING.value:   "wine",
    # SOFT_DRINK intentionally not mapped — not a card bucket.

    # From _classify_category() name-fallback (Python deriver buckets)
    "beer":              "beer",
    "wine":              "wine",
    "cocktails":         "cocktails",
    "premium_cocktails": "premium_cocktails",
    "food":              "food",
    # "mixers", "supply", "spirits" intentionally not mapped.
}


def _resolve_category(product: Product) -> str:
    """Hybrid resolver: DB enum first, name-fallback otherwise.

    Returns the GRANULAR category string. The caller decides whether
    to use it as-is (top-5 drinks) or roll up to a display bucket
    (bar cards).
    """
    if product.category is not None:
        return product.category.value
    return _classify_category(product.name)


def _bucket_for(category: str) -> DisplayBucket | None:
    """Map a granular category to a card bucket, or None if hidden."""
    return _ROLLUP_TO_BUCKET.get(category)


# ─── Service ─────────────────────────────────────────────────────────────

class BarCategoryTotalsService:
    """Reads live StockTransaction data and aggregates per (bar, category)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> EventBarCategoryTotalsResponse | None:
        """Returns the per-bar category totals for an event.

        Returns None if the event is not found for this tenant.
        Returns a response with bars=[] if the event exists but has no
        revenue-producing transactions yet (empty live event).
        """
        # 1. Verify event belongs to tenant
        ev = (await self.db.execute(
            select(Event.id).where(
                Event.id == event_id, Event.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()
        if ev is None:
            return None

        # 2. Pull every revenue-producing (bar, product, qty, price) row
        revenue_expr = (
            func.sum(StockTransaction.qty * StockTransaction.price_cents)
            / Decimal("100")
        ).label("revenue_eur")
        units_expr = func.sum(StockTransaction.qty).label("units")
        txn_count_expr = func.count(StockTransaction.id).label("txn_count")

        stmt = (
            select(
                Bar.id.label("bar_id"),
                Bar.name.label("bar_name"),
                Product.id.label("product_id"),
                Product.name.label("product_name"),
                Product.category.label("product_category"),
                units_expr,
                revenue_expr,
                txn_count_expr,
            )
            .join(StockTransaction, StockTransaction.bar_id == Bar.id)
            .join(Product, Product.id == StockTransaction.product_id)
            .where(
                StockTransaction.tenant_id == tenant_id,
                StockTransaction.event_id == event_id,
                StockTransaction.source.in_(REVENUE_SOURCES),
                StockTransaction.price_cents.is_not(None),
            )
            .group_by(
                Bar.id, Bar.name,
                Product.id, Product.name, Product.category,
            )
            .order_by(Bar.name, desc("units"))
        )
        rows = (await self.db.execute(stmt)).all()

        # 3. Build a fake Product instance for the resolver (we have the
        # category + name from the SQL row, no need to re-fetch).
        # Aggregate per bar.
        per_bar: dict[UUID, dict] = {}
        for r in rows:
            bar_id = r.bar_id
            if bar_id not in per_bar:
                per_bar[bar_id] = {
                    "bar_name": r.bar_name,
                    "buckets": defaultdict(lambda: {"units": 0, "revenue_eur": Decimal(0)}),
                    "products": [],   # for top-5 ranking
                    "total_units": 0,
                    "total_revenue": Decimal(0),
                }
            slot = per_bar[bar_id]

            # Resolve granular category for this (bar, product) row
            granular_category: str
            if r.product_category is not None:
                granular_category = r.product_category.value
            else:
                granular_category = _classify_category(r.product_name)

            units = int(r.units or 0)
            revenue = Decimal(str(r.revenue_eur or 0))
            slot["total_units"] += units
            slot["total_revenue"] += revenue

            # Roll up to display bucket (may be None → hidden from card,
            # but still counted in totals above)
            bucket = _bucket_for(granular_category)
            if bucket is not None:
                slot["buckets"][bucket]["units"] += units
                slot["buckets"][bucket]["revenue_eur"] += revenue

            # Top-5 candidate: only DRINK categories.
            # Food and supply are excluded from "top drinks."
            if bucket in ("beer", "cocktails", "premium_cocktails", "wine"):
                slot["products"].append({
                    "product_name": r.product_name,
                    "category": granular_category,
                    "units": units,
                    "revenue_eur": revenue,
                })

        # 4. Materialize response
        bars: list[BarCategoryTotals] = []
        for bar_id, slot in per_bar.items():
            categories = [
                BarCategoryBucket(bucket=b, units=v["units"], revenue_eur=v["revenue_eur"])
                for b, v in slot["buckets"].items()
            ]
            categories.sort(key=lambda c: -c.units)
            top_5 = sorted(slot["products"], key=lambda p: -p["units"])[:5]
            bars.append(BarCategoryTotals(
                bar_id=bar_id,
                bar_name=slot["bar_name"],
                categories=categories,
                top_5_drinks=[BarTopDrink(**p) for p in top_5],
                total_units=slot["total_units"],
                total_revenue_eur=slot["total_revenue"],
            ))
        bars.sort(key=lambda b: b.bar_name)

        return EventBarCategoryTotalsResponse(event_id=event_id, bars=bars)
