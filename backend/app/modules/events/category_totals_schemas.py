"""Schemas for GET /events/{event_id}/bar-category-totals.

This endpoint powers Omar's redesigned dashboard:
  - Bar cards show units + revenue rolled up to 5 buckets
    (beer / cocktails / premium_cocktails / wine / food)
  - Top 5 drinks per bar with specific product name + granular category

Category strategy (locked May 27 2026 with Hesam):
  Source of truth: Product.category DB enum (granular: beer_bottle,
    wine_red, basic_cocktail, premium_cocktail, etc.) when set.
    Fallback: _classify_category() by product name when DB value is NULL.
  Display: rolled up to 4+1 buckets on cards. Granular preserved in
    top-5 drinks so Omar sees "Cocktail signature" tagged premium_cocktail.

Spec: dashboard redesign LOCKED May 27 (post-Chrome-capture).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# 5 visible buckets on the bar card. Everything else
# (mixers/supply/spirits) is folded into the closest bucket
# or hidden by the frontend.
DisplayBucket = Literal[
    "beer", "cocktails", "premium_cocktails", "wine", "food",
]


class BarCategoryBucket(BaseModel):
    """One bucket row on a bar card. Already rolled up for display."""
    bucket: DisplayBucket
    units: int = Field(ge=0)
    revenue_eur: Decimal


class BarTopDrink(BaseModel):
    """One row in the per-bar top-5 list.

    `category` is the GRANULAR Product.category value (or the name-derived
    fallback), so Omar sees specific labels like 'premium_cocktail'.
    """
    product_name: str
    category: str
    units: int = Field(ge=0)
    revenue_eur: Decimal


class BarCategoryTotals(BaseModel):
    """One bar's slice of the response."""
    bar_id: UUID
    bar_name: str
    categories: list[BarCategoryBucket] = Field(default_factory=list)
    top_5_drinks: list[BarTopDrink] = Field(default_factory=list, max_length=5)
    total_units: int = Field(ge=0)
    total_revenue_eur: Decimal


class EventBarCategoryTotalsResponse(BaseModel):
    """Top-level response."""
    event_id: UUID
    bars: list[BarCategoryTotals] = Field(default_factory=list)
