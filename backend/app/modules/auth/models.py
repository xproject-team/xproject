"""SQLAlchemy ORM models for the auth module.

Contains:
  - Tenant: the root multi-tenancy entity (inherits Base directly)
  - User:   belongs to a tenant (inherits TenantScopedModel)
"""
from datetime import datetime, timezone
from enum import Enum as PyEnum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.tenancy import TenantScopedModel, _utcnow


class UserRole(str, PyEnum):
    """Valid user roles. Stored as a Postgres ENUM type."""
    OWNER = "owner"
    MANAGER = "manager"
    BARTENDER = "bartender"
    WAREHOUSE = "warehouse"


class Tenant(Base):
    """Root multi-tenancy entity. Every other tenant-scoped row references this.

    A Tenant typically represents one customer company (e.g. 'Noma Group').
    Deleting a tenant cascades to every row in every table that references it.
    """
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=_utcnow, onupdate=_utcnow,
    )


class User(TenantScopedModel):
    """Application user. Belongs to exactly one tenant."""
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True,
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=True),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
