"""SQLAlchemy ORM models for the auth module.

Contains:
  - Tenant: the root multi-tenancy entity (inherits Base directly)
  - User:   belongs to a tenant (inherits TenantScopedModel)
"""
from datetime import datetime, timezone
from enum import Enum as PyEnum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.tenancy import TenantScopedModel, _utcnow


class UserRole(str, PyEnum):
    """Valid user roles. Stored as a Postgres ENUM type.

    BARTENDER and WAREHOUSE are retired (Phase 2 two-role model): the
    members stay defined because historical rows still carry them, but
    they are excluded from ACTIVE_ROLES below — no login, token, or
    grant may use them.
    """
    OWNER = "owner"
    MANAGER = "manager"
    BARTENDER = "bartender"
    WAREHOUSE = "warehouse"


# Roles a session may authenticate or act as. Everything not in here is
# retired: rejected at login, rejected on token validation, and never
# offered by the frontend role picker.
ACTIVE_ROLES: frozenset[UserRole] = frozenset({UserRole.OWNER, UserRole.MANAGER})


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
    # Bar assignment (Manager / Bartender belong to ONE bar; Owner / Warehouse have NULL)
    bar_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("bars.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Multi-role: every role this user is authorized to act as.
    # The user's *active* role at any given moment lives in the JWT (Phase 1B).
    # The legacy `role` column above is kept until Phase 1D for backward compat.
    role_assignments: Mapped[list["UserRoleAssignment"]] = relationship(
        "UserRoleAssignment",
        primaryjoin="User.id == foreign(UserRoleAssignment.user_id)",
        lazy="selectin",
        cascade="all, delete-orphan",
        single_parent=True,
    )


class UserRoleAssignment(Base):
    """One row per (user, role) authorization grant.

    Companion to the legacy `User.role` column — that column tracks the user's
    *primary* role for backward compatibility; this table tracks every role a
    user is *authorized* to act as. A user with both Owner and Manager rights
    has two rows here.

    Created by migration `p1_add_user_roles_table`. Not tenant-scoped: a user
    already belongs to exactly one tenant via `User.tenant_id`, and that
    scoping cascades naturally through the foreign key.
    """
    __tablename__ = "user_roles"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=True, create_type=False),
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    # Owner who granted this role. NULL for system-assigned (initial backfill).
    assigned_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
