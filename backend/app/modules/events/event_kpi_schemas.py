"""Schemas for GET /events/{event_id}/kpi-summary.

Event-level KPI rollup for the redesigned dashboard top strip
(dashboard redesign LOCKED with Hesam, 2026):

  - Total Revenue = GROSS drinks (100%) + food (GROSS, pre-split) +
                    any confirmed revenue not yet mapped to a bar
                    (unmapped_revenue_eur — see below). NOT net of the
                    food-vendor share; that NET figure lives on
                    food.net_revenue_eur as a side field, and the fully
                    correct owner take-home (net of deposits returned,
                    VAT, and the food-vendor share) lives in the
                    Revenue Breakdown modal
                    (RevenueBreakdownService.OwnerWaterfall), not here.
  - Drinks        = units + revenue, broken into 4 families
                    (cocktails / beer / wine / soft; "other" catches
                    anything unmapped so totals reconcile)
  - Food          = units + GROSS revenue, broken down by FoodType,
                    plus the event's revenue-share % and Omar's NET cut
  - unmapped_revenue_eur = confirmed EventOrder revenue whose POS shop
                    has no Bar mapping yet (bar_id IS NULL). Included in
                    total_revenue_eur (fixed 2026-08, F-01 — previously
                    silently dropped), but NOT in drinks/food.revenue_eur,
                    since there's no bar to attribute it to either one.

Food is a partnership: the food company keeps (100 - share)% of gross,
Omar keeps share%. One share % per event (same across all trucks),
captured at Create Event. A NULL share means 100% (Omar keeps all) —
mirrors the wizard's "blank = 100%" copy.

Units and the drinks/food-family breakdown come from StockTransaction
(SUM(qty * price_cents) / 100 over revenue-producing rows), same as the
per-bar aggregator (category_totals_service). The euro totals
(total_revenue_eur, drinks.revenue_eur, food.gross_revenue_eur,
unmapped_revenue_eur) come from EventOrder.fiscal_gross_cents instead —
see event_kpi_service.py's module docstring for why.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# 4 visible drink families + "other" catch-all (spirits, mixers, deposits
# typed as drink, etc.) so drink totals always reconcile to the breakdown.
DrinkFamily = Literal["cocktails", "beer", "wine", "soft", "other"]


class DrinkCategoryLine(BaseModel):
    """One drink family in the breakdown."""
    family: DrinkFamily
    units: int = Field(ge=0)
    revenue_eur: Decimal


class FoodTypeLine(BaseModel):
    """One food type in the breakdown. revenue_eur is GROSS (pre-share)."""
    food_type: str          # FoodType value, or "other" for untyped food
    units: int = Field(ge=0)
    revenue_eur: Decimal


class DrinksSummary(BaseModel):
    """Drinks roll-up. revenue_eur is 100% Omar (no partnership split)."""
    units: int = Field(ge=0)
    revenue_eur: Decimal
    by_category: list[DrinkCategoryLine] = Field(default_factory=list)


class FoodSummary(BaseModel):
    """Food roll-up with the partnership split applied.

    gross_revenue_eur : total food sales (100%)
    share_pct         : Omar's % (event.food_revenue_share_pct, default 100)
    net_revenue_eur   : Omar's cut = gross * share_pct / 100
    by_type           : per-FoodType GROSS breakdown
    """
    units: int = Field(ge=0)
    gross_revenue_eur: Decimal
    share_pct: int = Field(ge=0, le=100)
    net_revenue_eur: Decimal
    by_type: list[FoodTypeLine] = Field(default_factory=list)


class EventKpiSummary(BaseModel):
    """Top-level dashboard KPI response.

    total_revenue_eur = drinks.revenue_eur + food.gross_revenue_eur +
    unmapped_revenue_eur (GROSS, not net of the food-vendor share —
    see this module's top docstring). The headline number on the
    dashboard's "Total Revenue" tile.

    unmapped_revenue_eur is 0 for an event with no unmapped orders; the
    frontend should only surface it when > 0.
    """
    event_id: UUID
    total_revenue_eur: Decimal
    unmapped_revenue_eur: Decimal = Decimal("0.00")
    drinks: DrinksSummary
    food: FoodSummary
