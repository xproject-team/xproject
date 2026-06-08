"""Schemas for GET /events/{event_id}/menu-performance.

Full-menu performance view for the dashboard breakdown panel.

The menu is EventProduct (one row per bar+product). This endpoint shows
EVERY drink and food menu item with its units sold — including items that
sold ZERO — so Omar sees the whole list:

  drinks : grouped by category family (cocktails/beer/wine/soft/other),
           units TOTALLED across all bars (the 3 drink bars share one
           cocktail menu, so per-product totals are what matters)
  food   : grouped by TRUCK (bar), each truck listing its own items

Deposits/supply/ingredient lines are excluded — drink + food only.
Revenue per item is GROSS (drinks are 100% Omar anyway; the food
partnership split is surfaced on the Food KPI card, not here).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

DrinkFamily = Literal["cocktails", "beer", "wine", "soft", "other"]


class MenuItemLine(BaseModel):
    """One menu item with its sold units. units == 0 for unsold items."""
    product_id:   UUID
    product_name: str
    units:        int = Field(ge=0)
    revenue_eur:  Decimal


class DrinkCategoryGroup(BaseModel):
    """Drink items rolled under one family, totalled across all bars."""
    family:               DrinkFamily
    items:                list[MenuItemLine] = Field(default_factory=list)
    subtotal_units:       int = Field(ge=0)
    subtotal_revenue_eur: Decimal


class FoodTruckGroup(BaseModel):
    """Food items for one truck (bar)."""
    bar_id:               UUID
    bar_name:             str
    items:                list[MenuItemLine] = Field(default_factory=list)
    subtotal_units:       int = Field(ge=0)
    subtotal_revenue_eur: Decimal


class EventMenuPerformance(BaseModel):
    """Top-level menu-performance response."""
    event_id: UUID
    drinks:   list[DrinkCategoryGroup] = Field(default_factory=list)
    food:     list[FoodTruckGroup]     = Field(default_factory=list)
