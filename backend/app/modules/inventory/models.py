"""SQLAlchemy ORM models for the inventory module."""
from sqlalchemy import Column, Float, ForeignKey, Integer, String

from app.core.database import Base


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    bar_id = Column(Integer, nullable=False)
    sku = Column(String, nullable=False)
    name = Column(String, nullable=False)
    quantity = Column(Float, default=0.0)
    unit = Column(String, default="units")
    low_stock_threshold = Column(Float, default=10.0)
