"""SQLAlchemy ORM models for the events module."""
from sqlalchemy import Column, DateTime, Integer, String

from app.core.database import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    venue = Column(String, nullable=False)
    status = Column(String, default="pending")  # pending | active | ended
    created_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
