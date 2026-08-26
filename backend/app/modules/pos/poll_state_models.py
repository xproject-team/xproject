"""SQLAlchemy model for the slesh_poll_state table.

Kept in its own module to avoid polluting pos/schemas.py (which holds
Pydantic models for Slesh API responses, not DB models).

Spec: docs/slesh-integration-roadmap.md §B6.2 + §B6.4
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel
# Import Tenant so SQLAlchemy can resolve the tenant_id FK on SleshPollState:
# model registration happens at import time, so any module that USES
# SleshPollState pulls Tenant in too. (Standalone scripts should import
# app.models_registry instead of relying on per-module side effects.)
from app.modules.auth.models import Tenant  # noqa: F401 — imported for FK side effect


class SleshPollState(TenantScopedModel):
    """Cursor row tracking how far the Slesh poller has caught up.

    One row per (tenant_id, brand_id, experience_id) scope. The DB has a
    UNIQUE index enforcing this — see migration m1_add_slesh_poll_state.
    """
    __tablename__ = "slesh_poll_state"

    # tenant_id, id, created_at, updated_at come from TenantScopedModel.

    brand_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    experience_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    last_seen_ts: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    # Streak of consecutive failed poll cycles. Reset to 0 by
    # record_success(), incremented by record_failure() (poll_state.py).
    # Distinguishes "just had one blip" from "polling has been down for a
    # while" for GET /events/{event_id}/polling-health (migration aa7).
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )

    def __repr__(self) -> str:
        return (
            f"<SleshPollState(tenant={self.tenant_id} brand={self.brand_id} "
            f"exp={self.experience_id} cursor={self.last_seen_ts} "
            f"status={self.last_status})>"
        )


__all__ = ["SleshPollState"]
