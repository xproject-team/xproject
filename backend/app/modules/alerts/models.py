"""SQLAlchemy ORM models for the alerts module."""
from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.database import Base


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, nullable=False)
    rule_name = Column(String, nullable=False)
    severity = Column(String, nullable=False)  # info | warning | critical
    message = Column(String, nullable=False)
    acknowledged = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=True)
