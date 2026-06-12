"""Full-menu performance aggregator for the dashboard breakdown panel.

Builds (bar, product) pairs from the UNION of the event's menu
(EventProduct) and the distinct sold pairs from StockTransaction, then
LEFT-joins sold units onto each pair. Two consequences:
  - zero-sold menu items still appear (the original feature), and
  - sales for products not on the configured menu (or sales for an event
    with no menu configured yet) still appear, so the breakdown can
    never silently drop revenue that the strip is already counting.
Drinks are totalled per product across all bars and grouped by family;
food is grouped by truck (bar). Drink + food only.

Reuses the revenue/family contract from event_kpi_service (same
REVENUE_SOURCES, SUM(qty*price_cents)/100, drink-family resolver).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models import Bar
from app.modules.event_products.models import EventProduct
from app.modules.events.event_kpi_service import _drink_family, _enum_value, _money
from app.modules.events.menu_performance_schemas import (
    DrinkCategoryGroup,
    EventMenuPerformance,
    FoodTruckGroup,
    MenuItemLine,
)
from app.modules.events.models import Event
from app.modules.predictions.predictors.heuristic import REVENUE_SOURCES
from app.modules.products.models import Product, ProductType
from app.modules.stock_transactions.models import StockTransaction

_CENTS = Decimal("100")
_FAMILY_ORDER = ["cocktails", "beer", "wine", "soft", "other"]


class MenuPerformanceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_for_event(
        self, tenant_id: UUID, event_id: UUID,
    ) -> EventMenuPerformance | None:
        ev = (await self.db.execute(
            select(Event.id).where(
                Event.id == event_id, Event.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()
        if ev is None:
            return None

        # 1. The menu: one row per (bar, product), drink + food only.
        menu_stmt = (
            select(
                EventProduct.bar_id.label("bar_id"),
                Bar.name.label("bar_name"),
                Product.id.label("product_id"),
                Product.name.label("product_name"),
                Product.product_type.label("product_type"),
                Product.category.label("category"),
            )
            .select_from(EventProduct)
            .join(Product, Product.id == EventProduct.product_id)
            .join(Bar, Bar.id == EventProduct.bar_id)
            .where(
                EventProduct.tenant_id == tenant_id,
                EventProduct.event_id == event_id,
                Product.product_type.in_([ProductType.DRINK, ProductType.FOOD]),
            )
        )
        menu_rows = (await self.db.execute(menu_stmt)).all()

        # 2. Sold units + revenue per (bar, product).
        sold_stmt = (
            select(
                StockTransaction.bar_id.label("bar_id"),
                StockTransaction.product_id.label("product_id"),
                func.sum(StockTransaction.qty).label("units"),
                (func.sum(StockTransaction.qty * StockTransaction.price_cents)
                 / _CENTS).label("revenue_eur"),
            )
            .where(
                StockTransaction.tenant_id == tenant_id,
                StockTransaction.event_id == event_id,
                StockTransaction.source.in_(REVENUE_SOURCES),
                StockTransaction.price_cents.is_not(None),
            )
            .group_by(StockTransaction.bar_id, StockTransaction.product_id)
        )
        sold: dict[tuple[UUID, UUID], tuple[int, Decimal]] = {}
        for r in (await self.db.execute(sold_stmt)).all():
            sold[(r.bar_id, r.product_id)] = (
                int(r.units or 0), Decimal(str(r.revenue_eur or 0)),
            )

        # 3. Dedupe menu by (bar, product), split drinks/food.
        seen: dict[tuple[UUID, UUID], object] = {}
        for r in menu_rows:
            seen.setdefault((r.bar_id, r.product_id), r)

        # 3b. Sold-but-not-on-menu pairs: synthesize rows so the breakdown
        #     never silently drops revenue the strip is already counting.
        missing = set(sold.keys()) - set(seen.keys())
        if missing:
            extra_pids = {p for _, p in missing}
            extra_bids = {b for b, _ in missing}
            prod_rows = (await self.db.execute(
                select(
                    Product.id.label("product_id"),
                    Product.name.label("product_name"),
                    Product.product_type.label("product_type"),
                    Product.category.label("category"),
                ).where(
                    Product.tenant_id == tenant_id,
                    Product.id.in_(extra_pids),
                    Product.product_type.in_([ProductType.DRINK, ProductType.FOOD]),
                )
            )).all()
            prod_info = {r.product_id: r for r in prod_rows}
            bar_rows = (await self.db.execute(
                select(Bar.id.label("bar_id"), Bar.name.label("bar_name"))
                .where(Bar.tenant_id == tenant_id, Bar.id.in_(extra_bids))
            )).all()
            bar_name_by_id = {r.bar_id: r.bar_name for r in bar_rows}
            for bid, pid in missing:
                pr = prod_info.get(pid)
                if pr is None:
                    continue   # not drink/food, or product missing -> drop
                bn = bar_name_by_id.get(bid)
                if bn is None:
                    continue   # bar missing -> defensive
                seen[(bid, pid)] = SimpleNamespace(
                    bar_id=bid, bar_name=bn,
                    product_id=pid, product_name=pr.product_name,
                    product_type=pr.product_type, category=pr.category,
                )

        drink_acc: dict[UUID, dict] = {}   # per product, totalled across bars
        food_acc: dict[UUID, dict] = {}    # per truck (bar) -> items

        for (bar_id, product_id), r in seen.items():
            ptype = _enum_value(r.product_type)
            units, revenue = sold.get((bar_id, product_id), (0, Decimal(0)))
            if ptype == "drink":
                cat = _enum_value(r.category) if r.category is not None else None
                family = _drink_family(cat, r.product_name or "")
                slot = drink_acc.setdefault(product_id, {
                    "name": r.product_name, "family": family,
                    "units": 0, "revenue": Decimal(0),
                })
                slot["units"] += units
                slot["revenue"] += revenue
            elif ptype == "food":
                truck = food_acc.setdefault(bar_id, {
                    "bar_name": r.bar_name, "items": {},
                })
                truck["items"][product_id] = {
                    "name": r.product_name, "units": units, "revenue": revenue,
                }

        # 4. Drinks grouped by family (fixed order).
        by_family: dict[str, list[dict]] = defaultdict(list)
        for pid, d in drink_acc.items():
            by_family[d["family"]].append({"pid": pid, **d})

        drink_groups: list[DrinkCategoryGroup] = []
        for fam in _FAMILY_ORDER:
            items = by_family.get(fam)
            if not items:
                continue
            items.sort(key=lambda x: (-x["units"], x["name"].lower()))
            drink_groups.append(DrinkCategoryGroup(
                family=fam,
                items=[
                    MenuItemLine(product_id=x["pid"], product_name=x["name"],
                                 units=x["units"], revenue_eur=_money(x["revenue"]))
                    for x in items
                ],
                subtotal_units=sum(x["units"] for x in items),
                subtotal_revenue_eur=_money(
                    sum((x["revenue"] for x in items), Decimal(0))
                ),
            ))

        # 5. Food grouped by truck (sorted by busiest truck).
        food_groups: list[FoodTruckGroup] = []
        for bar_id, truck in food_acc.items():
            ordered = sorted(
                truck["items"].items(),
                key=lambda kv: (-kv[1]["units"], kv[1]["name"].lower()),
            )
            food_groups.append(FoodTruckGroup(
                bar_id=bar_id,
                bar_name=truck["bar_name"],
                items=[
                    MenuItemLine(product_id=pid, product_name=v["name"],
                                 units=v["units"], revenue_eur=_money(v["revenue"]))
                    for pid, v in ordered
                ],
                subtotal_units=sum(v["units"] for _, v in ordered),
                subtotal_revenue_eur=_money(
                    sum((v["revenue"] for _, v in ordered), Decimal(0))
                ),
            ))
        food_groups.sort(key=lambda g: (-g.subtotal_units, g.bar_name.lower()))

        return EventMenuPerformance(
            event_id=event_id, drinks=drink_groups, food=food_groups,
        )
