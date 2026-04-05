"""SQLAlchemy ORM models for the predictions module."""
from sqlalchemy import Column, DateTime, Float, Integer, String

from app.core.database import Base


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, nullable=False)
    sku = Column(String, nullable=False)
    predicted_demand = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    horizon_hours = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=True)
