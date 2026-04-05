"""SQLAlchemy ORM models for the reports module."""
from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    narrative = Column(Text, nullable=True)
    pdf_path = Column(String, nullable=True)
    generated_at = Column(DateTime, nullable=True)
