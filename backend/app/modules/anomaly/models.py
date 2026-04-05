"""SQLAlchemy ORM models for the anomaly detection module."""
from sqlalchemy import Column, DateTime, Float, Integer, String

from app.core.database import Base


class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, nullable=False)
    detector = Column(String, nullable=False)
    sku = Column(String, nullable=True)
    score = Column(Float, nullable=False)
    description = Column(String, nullable=False)
    detected_at = Column(DateTime, nullable=True)
