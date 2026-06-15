"""RevenueBreakdownService — compose the popup payload from event_orders + bars.

Source of truth: event_orders rows (one per Slesh order) populated by the
ingester / backfill script. Bar classification (drinks/food/merch) is read
from Bar.bar_type — data-driven, never name-matched. Food share % is
per-event from Event.food_revenue_share_pct.

All money is stored as int cents in the DB; conversion to Decimal EUR
happens at the response boundary, two-decimal-quantized.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bars.models import Bar
from app.modules.events.models import Event, EventOrder

from .revenue_breakdown_schemas import (
    BarSale,
    CashFlowBreakdown,
    Diagnostics,
    DepositsBreakdown,
    FiscalBreakdown,
    OwnerTakeHome,
    RevenueBreakdown,
    SalesBreakdown,
)


# ---------- helpers ----------

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


# ---------- service ----------

class RevenueBreakdownService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def compute(self, tenant_id: UUID, event_id: UUID) -> RevenueBreakdown:
        event = await self._load_event(tenant_id, event_id)
        per_type = await self._totals_by_order_type(tenant_id, event_id)
        per_bar = await self._totals_by_bar(tenant_id, event_id)
        deposits = await self._deposit_split(tenant_id, event_id)

        # ----- top-level totals -----
        all_subtotal = sum(r["subtotal"] for r in per_type.values())
        all_vat = sum(r["vat"] for r in per_type.values())
        all_fiscal_gross = sum(r["fiscal_gross"] for r in per_type.values())
        all_fiscal_net = sum(r["fiscal_net"] for r in per_type.values())
        all_discount = sum(r["discount"] for r in per_type.values())
        all_cart_lines = sum(r["cart_lines"] for r in per_type.values())
        all_count = sum(r["count"] for r in per_type.values())

        exp = per_type.get("experience", {"subtotal": 0, "count": 0})
        cash = per_type.get("cash-desk", {"subtotal": 0, "count": 0})

        # ----- sales by bar -----
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
            # merch falls out of the per-bar lists — it's reported only via cash-desk total

        sales = SalesBreakdown(
            drinks_total_eur=_cents_to_eur(drinks_total),
            drinks_by_bar=drinks_bars,
            food_total_eur=_cents_to_eur(food_total),
            food_by_bar=food_bars,
            cash_desk_eur=_cents_to_eur(cash["subtotal"]),
            subtotal_eur=_cents_to_eur(drinks_total + food_total + cash["subtotal"]),
        )

        # ----- deposits -----
        collected_eur = _cents_to_eur(deposits["collected"])
        returned_eur = _cents_to_eur(deposits["returned"])
        forfeited_eur = collected_eur - returned_eur
        deposits_b = DepositsBreakdown(
            collected_eur=collected_eur,
            returned_eur=returned_eur,
            forfeited_eur=forfeited_eur,
            return_rate_pct=_safe_pct(returned_eur, collected_eur),
        )

        # ----- fiscal -----
        fiscal_b = FiscalBreakdown(
            vat_eur=_cents_to_eur(all_vat),
            fiscal_gross_eur=_cents_to_eur(all_fiscal_gross),
            fiscal_net_eur=_cents_to_eur(all_fiscal_net),
            discounts_eur=_cents_to_eur(all_discount),
        )

        # ----- cash flow (ricariche + unspent are placeholders until manual entry) -----
        cash_flow_b = CashFlowBreakdown(
            ricariche_eur=None,
            cash_desk_in_eur=_cents_to_eur(cash["subtotal"]),
            spent_at_bars_eur=_cents_to_eur(drinks_total + food_total),
            unspent_balance_eur=None,
        )

        # ----- owner take-home -----
        share_pct = int(event.food_revenue_share_pct or 30)
        drinks_owner = _cents_to_eur(drinks_total)
        food_gross = _cents_to_eur(food_total)
        food_share = (food_gross * Decimal(share_pct) / Decimal(100)).quantize(Decimal("0.01"))
        cash_desk_owner = _cents_to_eur(cash["subtotal"])
        owner = OwnerTakeHome(
            drinks_eur=drinks_owner,
            deposits_forfeited_eur=forfeited_eur,
            food_gross_eur=food_gross,
            food_share_pct=share_pct,
            food_share_eur=food_share,
            cash_desk_eur=cash_desk_owner,
            total_eur=drinks_owner + forfeited_eur + food_share + cash_desk_owner,
        )

        # ----- diagnostics -----
        diag = Diagnostics(
            order_count=all_count,
            experience_order_count=exp["count"],
            cash_desk_order_count=cash["count"],
            cart_line_count=all_cart_lines,
        )

        return RevenueBreakdown(
            event_id=event_id,
            event_name=event.name,
            total_billed_eur=_cents_to_eur(all_subtotal + all_vat),
            transaction_count=all_count,
            cancelled_eur=Decimal("0.00"),
            sales=sales,
            deposits=deposits_b,
            fiscal=fiscal_b,
            cash_flow=cash_flow_b,
            owner_take_home=owner,
            diagnostics=diag,
        )

    # ---------- queries ----------

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

    async def _totals_by_order_type(
        self, tenant_id: UUID, event_id: UUID
    ) -> dict[str, dict]:
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

    async def _totals_by_bar(
        self, tenant_id: UUID, event_id: UUID
    ) -> list[dict]:
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

    async def _deposit_split(
        self, tenant_id: UUID, event_id: UUID
    ) -> dict[str, int]:
        # Positive deposit_cents = collected; negative = returned. We sum each
        # side separately so the popup can show the gross flow, not just the net.
        collected_stmt = (
            select(func.coalesce(func.sum(EventOrder.deposit_cents), 0))
            .where(
                EventOrder.tenant_id == tenant_id,
                EventOrder.event_id == event_id,
                EventOrder.deposit_cents > 0,
            )
        )
        returned_stmt = (
            select(func.coalesce(func.sum(EventOrder.deposit_cents), 0))
            .where(
                EventOrder.tenant_id == tenant_id,
                EventOrder.event_id == event_id,
                EventOrder.deposit_cents < 0,
            )
        )
        collected = int((await self.db.execute(collected_stmt)).scalar() or 0)
        returned = abs(int((await self.db.execute(returned_stmt)).scalar() or 0))
        return {"collected": collected, "returned": returned}
