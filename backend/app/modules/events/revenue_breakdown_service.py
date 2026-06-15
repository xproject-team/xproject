"""RevenueBreakdownService - compose the popup payload from event_orders + bars.

See docs/revenue-calculation-bible.md for the canonical math.

Source of truth: event_orders rows with status != 'refunded'. Bar classification
(drinks/food/mixed/merch) is read from Bar.bar_type. Food share % is per-event
from Event.food_revenue_share_pct, expressed as OWNER's share (30 means
owner takes 30%, vendor takes 70%).

All money is stored as int cents in the DB; conversion to Decimal EUR happens
at the response boundary, two-decimal-quantized.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models import Bar
from app.modules.events.models import Event, EventOrder
from app.modules.products.models import Product
from app.modules.stock_transactions.models import StockTransaction

from .revenue_breakdown_schemas import (
    BarSale,
    CashFlowBreakdown,
    Diagnostics,
    DepositsBreakdown,
    FiscalBreakdown,
    OwnerWaterfall,
    RevenueBreakdown,
    SalesBreakdown,
)


def _cents_to_eur(cents: int | None) -> Decimal:
    if not cents:
        return Decimal("0.00")
    return (Decimal(int(cents)) / Decimal(100)).quantize(Decimal("0.01"))


def _safe_pct(num: Decimal, den: Decimal) -> float | None:
    if den == 0:
        return None
    return float((num / den * 100).quantize(Decimal("0.1")))


def _normalize_bar_type(raw) -> str:
    if raw is None:
        return "unknown"
    if hasattr(raw, "value"):
        return raw.value
    return str(raw)


REFUNDED_STATUS = "refunded"


class RevenueBreakdownService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def compute(self, tenant_id: UUID, event_id: UUID) -> RevenueBreakdown:
        event = await self._load_event(tenant_id, event_id)
        per_type = await self._totals_by_order_type(tenant_id, event_id)
        per_bar = await self._totals_by_bar(tenant_id, event_id)
        deposits_raw = await self._deposit_split(tenant_id, event_id)
        refunded_count = await self._refunded_order_count(tenant_id, event_id)

        all_subtotal = sum(r["subtotal"] for r in per_type.values())
        all_vat = sum(r["vat"] for r in per_type.values())
        all_fiscal_gross = sum(r["fiscal_gross"] for r in per_type.values())
        all_fiscal_net = sum(r["fiscal_net"] for r in per_type.values())
        all_discount = sum(r["discount"] for r in per_type.values())
        all_cart_lines = sum(r["cart_lines"] for r in per_type.values())
        all_count = sum(r["count"] for r in per_type.values())

        exp = per_type.get("experience", {"subtotal": 0, "count": 0})
        cash = per_type.get("cash-desk", {"subtotal": 0, "count": 0})

        drinks_bars: list[BarSale] = []
        food_bars: list[BarSale] = []
        drinks_total = 0
        food_total = 0
        for row in per_bar:
            bt = row["bar_type"]
            bs = BarSale(
                bar_id=row["bar_id"],
                bar_name=row["bar_name"],
                bar_type=bt,
                revenue_eur=_cents_to_eur(row["subtotal"]),
                order_count=row["count"],
            )
            if bt in ("drinks", "mixed"):
                drinks_bars.append(bs)
                drinks_total += row["subtotal"]
            elif bt == "food":
                food_bars.append(bs)
                food_total += row["subtotal"]

        sales = SalesBreakdown(
            drinks_total_eur=_cents_to_eur(drinks_total),
            drinks_by_bar=drinks_bars,
            food_total_eur=_cents_to_eur(food_total),
            food_by_bar=food_bars,
            cash_desk_eur=_cents_to_eur(cash["subtotal"]),
            subtotal_eur=_cents_to_eur(drinks_total + food_total + cash["subtotal"]),
        )

        collected_eur = _cents_to_eur(deposits_raw["collected"])
        returned_eur = _cents_to_eur(deposits_raw["returned"])
        forfeited_eur = collected_eur - returned_eur
        collected_units = int(deposits_raw["collected_units"])
        returned_units = int(deposits_raw["returned_units"])
        deposits_b = DepositsBreakdown(
            collected_eur=collected_eur,
            collected_units=collected_units,
            returned_eur=returned_eur,
            returned_units=returned_units,
            forfeited_eur=forfeited_eur,
            forfeited_units=collected_units - returned_units,
            return_rate_pct=_safe_pct(returned_eur, collected_eur),
        )

        fiscal_b = FiscalBreakdown(
            vat_eur=_cents_to_eur(all_vat),
            fiscal_gross_eur=_cents_to_eur(all_fiscal_gross),
            fiscal_net_eur=_cents_to_eur(all_fiscal_net),
            discounts_eur=_cents_to_eur(all_discount),
        )

        cash_flow_b = CashFlowBreakdown(
            ricariche_eur=None,
            cash_desk_in_eur=_cents_to_eur(cash["subtotal"]),
            spent_at_bars_eur=_cents_to_eur(drinks_total + food_total),
            unspent_balance_eur=None,
        )

        share_pct = int(event.food_revenue_share_pct or 30)
        food_owner_share_cents = int(food_total * share_pct / 100)
        food_vendor_share_cents = food_total - food_owner_share_cents
        net_takehome_cents = (
            all_subtotal
            - deposits_raw["returned"]
            - all_vat
            - food_vendor_share_cents
        )
        owner = OwnerWaterfall(
            gross_revenue_eur=_cents_to_eur(all_subtotal),
            minus_deposits_returned_eur=_cents_to_eur(deposits_raw["returned"]),
            minus_vat_eur=_cents_to_eur(all_vat),
            minus_food_vendor_share_eur=_cents_to_eur(food_vendor_share_cents),
            net_takehome_eur=_cents_to_eur(net_takehome_cents),
            food_owner_share_pct=share_pct,
            food_owner_share_eur=_cents_to_eur(food_owner_share_cents),
            food_vendor_share_pct=100 - share_pct,
        )

        diag = Diagnostics(
            order_count=all_count,
            experience_order_count=exp["count"],
            cash_desk_order_count=cash["count"],
            cart_line_count=all_cart_lines,
            refunded_order_count=refunded_count,
        )

        return RevenueBreakdown(
            event_id=event_id,
            event_name=event.name,
            total_billed_eur=_cents_to_eur(all_subtotal),
            transaction_count=all_count,
            cancelled_eur=Decimal("0.00"),
            sales=sales,
            deposits=deposits_b,
            fiscal=fiscal_b,
            cash_flow=cash_flow_b,
            owner_waterfall=owner,
            diagnostics=diag,
        )

    async def _load_event(self, tenant_id: UUID, event_id: UUID) -> Event:
        stmt = (
            select(Event)
            .where(Event.tenant_id == tenant_id, Event.id == event_id)
            .limit(1)
        )
        result = await self.db.execute(stmt)
        event = result.scalar_one_or_none()
        if event is None:
            raise NoResultFound(f"Event {event_id} not found for tenant {tenant_id}")
        return event

    async def _totals_by_order_type(self, tenant_id: UUID, event_id: UUID) -> dict[str, dict]:
        stmt = (
            select(
                EventOrder.order_type,
                func.coalesce(func.sum(EventOrder.subtotal_cents), 0).label("subtotal"),
                func.coalesce(func.sum(EventOrder.vat_cents), 0).label("vat"),
                func.coalesce(func.sum(EventOrder.deposit_cents), 0).label("deposit"),
                func.coalesce(func.sum(EventOrder.fiscal_gross_cents), 0).label("fiscal_gross"),
                func.coalesce(func.sum(EventOrder.fiscal_net_cents), 0).label("fiscal_net"),
                func.coalesce(func.sum(EventOrder.discount_cents), 0).label("discount"),
                func.coalesce(func.sum(EventOrder.cart_line_count), 0).label("cart_lines"),
                func.count().label("count"),
            )
            .where(
                EventOrder.tenant_id == tenant_id,
                EventOrder.event_id == event_id,
                EventOrder.status != REFUNDED_STATUS,
            )
            .group_by(EventOrder.order_type)
        )
        result = await self.db.execute(stmt)
        return {
            row.order_type: {
                "subtotal": int(row.subtotal),
                "vat": int(row.vat),
                "deposit": int(row.deposit),
                "fiscal_gross": int(row.fiscal_gross),
                "fiscal_net": int(row.fiscal_net),
                "discount": int(row.discount),
                "cart_lines": int(row.cart_lines),
                "count": int(row.count),
            }
            for row in result.all()
        }

    async def _totals_by_bar(self, tenant_id: UUID, event_id: UUID) -> list[dict]:
        stmt = (
            select(
                Bar.id.label("bar_id"),
                Bar.name.label("bar_name"),
                Bar.bar_type.label("bar_type"),
                func.coalesce(func.sum(EventOrder.subtotal_cents), 0).label("subtotal"),
                func.count().label("count"),
            )
            .join(EventOrder, EventOrder.bar_id == Bar.id)
            .where(
                EventOrder.tenant_id == tenant_id,
                EventOrder.event_id == event_id,
                EventOrder.bar_id.is_not(None),
                EventOrder.status != REFUNDED_STATUS,
            )
            .group_by(Bar.id, Bar.name, Bar.bar_type)
            .order_by(func.sum(EventOrder.subtotal_cents).desc())
        )
        result = await self.db.execute(stmt)
        return [
            {
                "bar_id": row.bar_id,
                "bar_name": row.bar_name,
                "bar_type": _normalize_bar_type(row.bar_type),
                "subtotal": int(row.subtotal),
                "count": int(row.count),
            }
            for row in result.all()
        ]

    async def _refunded_order_count(self, tenant_id: UUID, event_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(EventOrder)
            .where(
                EventOrder.tenant_id == tenant_id,
                EventOrder.event_id == event_id,
                EventOrder.status == REFUNDED_STATUS,
            )
        )
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    async def _deposit_split(self, tenant_id: UUID, event_id: UUID) -> dict[str, int]:
        deposit_prod_subq = (
            select(Product.id)
            .where(
                Product.tenant_id == tenant_id,
                or_(
                    Product.name == "Bicchiere",
                    Product.name.op("ILIKE")("Cauzione%"),
                ),
            )
            .scalar_subquery()
        )
        stmt = (
            select(
                StockTransaction.pos_line_status,
                func.coalesce(
                    func.sum(StockTransaction.qty * StockTransaction.price_cents),
                    0,
                ).label("total_cents"),
                func.coalesce(func.sum(StockTransaction.qty), 0).label("units"),
            )
            .where(
                StockTransaction.tenant_id == tenant_id,
                StockTransaction.event_id == event_id,
                StockTransaction.product_id.in_(deposit_prod_subq),
            )
            .group_by(StockTransaction.pos_line_status)
        )
        result = await self.db.execute(stmt)
        collected_cents = 0
        returned_cents = 0
        collected_units = 0
        returned_units = 0
        for row in result.all():
            cents = int(row.total_cents or 0)
            units = int(row.units or 0)
            if row.pos_line_status == "confirmed":
                collected_cents = cents
                collected_units = units
            elif row.pos_line_status == "refunded":
                returned_cents = cents
                returned_units = units
        return {
            "collected": collected_cents,
            "returned": returned_cents,
            "collected_units": collected_units,
            "returned_units": returned_units,
        }
