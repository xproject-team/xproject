"""Pydantic schemas for /events/{event_id}/bar-supplier-stock."""
from __future__ import annotations

from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


StockStatus = Literal["healthy", "low", "critical"]


class BarSupplierStockItem(BaseModel):
    """One row per (bar, supplier_product) with depletion math."""
    bar_id:              UUID
    bar_name:            str
    supplier_product_id: UUID
    item_name:           str
    dispatched_units:    float  # in default_unit
    dispatched_ml:       float
    consumed_ml:           float
    consumed_ml_certain:   float
    consumed_ml_uncertain: float
    remaining_ml:          float
    remaining_pct:       float = Field(ge=0)
    status:              StockStatus
    threshold_pct_warn:  float
    threshold_pct_empty: float
    accurate:            bool   # True = sole-ingredient (no worst-case)


class BarAggregatedStock(BaseModel):
    """Per-bar Σ ml for the bar-card 'Stock Level' indicator."""
    bar_id:        UUID
    bar_name:      str
    dispatched_ml: float
    remaining_ml:  float
    pct:           float = Field(ge=0)
    status:        StockStatus


class BarSupplierStockResponse(BaseModel):
    event_id:     UUID
    items:        list[BarSupplierStockItem]
    by_bar:       list[BarAggregatedStock]
