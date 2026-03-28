"""SQLAlchemy ORM models for the auth module."""
from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # owner | manager | bartender | warehouse
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=True)
