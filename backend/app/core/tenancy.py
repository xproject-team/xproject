"""Multi-tenant base class — every tenant-scoped model inherits from this.

This file is the single most important SaaS-readiness guarantee in the
codebase. By forcing every business model to inherit from TenantScopedModel,
we make it impossible to accidentally create a table without a tenant_id
foreign key. This is the primary defense against cross-tenant data leaks.
"""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    """Return current time as timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class TenantScopedModel(Base):
    """Abstract base for every model that belongs to a tenant.

    Provides:
      - id:         UUID primary key (collision-safe, no ID enumeration)
      - tenant_id:  UUID foreign key to tenants.id (cascade on tenant delete)
      - created_at: timezone-aware timestamp, set automatically on insert
      - updated_at: timezone-aware timestamp, auto-updated on every change

    Usage:
        class Venue(TenantScopedModel):
            __tablename__ = "venues"
            name: Mapped[str] = mapped_column(String(255), nullable=False)
    """

    __abstract__ = True  # SQLAlchemy will not create a table for this class

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
