"""Schemas for GET /events/{event_id}/kpi-summary.

Event-level KPI rollup for the redesigned dashboard top strip
(dashboard redesign LOCKED with Hesam, 2026):

  - Total Revenue = Omar's NET take = drinks (100%) + food (x share %)
  - Drinks        = units + revenue, broken into 4 families
                    (cocktails / beer / wine / soft; "other" catches
                    anything unmapped so totals reconcile)
  - Food          = units + GROSS revenue, broken down by FoodType,
                    plus the event's revenue-share % and Omar's NET cut

Food is a partnership: the food company keeps (100 - share)% of gross,
Omar keeps share%. One share % per event (same across all trucks),
captured at Create Event. A NULL share means 100% (Omar keeps all) —
mirrors the wizard's "blank = 100%" copy.

Revenue is computed exactly like the per-bar aggregator
(category_totals_service): SUM(qty * price_cents) / 100 over
revenue-producing StockTransaction rows only.
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

    total_revenue_eur = drinks.revenue_eur + food.net_revenue_eur
    (Omar's NET take — the headline number on the dashboard).
    """
    event_id: UUID
    total_revenue_eur: Decimal
    drinks: DrinksSummary
    food: FoodSummary
