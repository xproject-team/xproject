"""SQLAlchemy ORM models for the warehouse module."""
from sqlalchemy import Column, DateTime, Integer, String

from app.core.database import Base


class ScanEvent(Base):
    __tablename__ = "scan_events"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, nullable=False)
    barcode = Column(String, nullable=False)
    sku = Column(String, nullable=True)
    action = Column(String, nullable=False)  # receive | dispatch | audit
    quantity = Column(Integer, nullable=False, default=1)
    scanned_by = Column(Integer, nullable=False)  # user_id
    scanned_at = Column(DateTime, nullable=True)
