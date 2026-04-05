"""Pydantic v2 request/response schemas for the inventory module."""
from pydantic import BaseModel


class InventoryItemCreate(BaseModel):
    event_id: int
    bar_id: int
    sku: str
    name: str
    quantity: float = 0.0
    unit: str = "units"
    low_stock_threshold: float = 10.0


class InventoryItemResponse(BaseModel):
    id: int
    event_id: int
    bar_id: int
    sku: str
    name: str
    quantity: float
    unit: str
    low_stock_threshold: float

    model_config = {"from_attributes": True}
