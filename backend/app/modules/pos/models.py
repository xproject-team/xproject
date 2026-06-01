"""SQLAlchemy ORM models for the pos module.

Currently contains:
  - SleshShopMatchProposal: pending name-matching decisions between
    Slesh shop IDs and existing bars. Owner approves/rejects each
    before the linkage is persisted on the bar.

See docs/e2e-validation-design.md (S4 — Name-matching UX).
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel


# ─── Status enum ──────────────────────────────────────────────────────────────
# Stored as a Postgres native enum (created in alembic migration v1).
# Decisions are append-only after the first transition out of pending.

class ShopMatchStatus(str, PyEnum):
    # Values match the Postgres enum, which uses UPPERCASE per the
    # codebase convention (see EventStatus + alembic migration v1).
    # SQLAlchemy serializes via member NAME, which on DB equals value
    # for this design.
    PENDING  = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SKIPPED  = "SKIPPED"


# ─── Model ────────────────────────────────────────────────────────────────────

class SleshShopMatchProposal(TenantScopedModel):
    """A pending match between a Slesh shop and a candidate bar.

    Created by the sync flow when an incoming Slesh shop has no
    matching bar.slesh_negozio_id. A best-effort fuzzy match against
    existing UNLINKED bars (rapidfuzz, normalized similarity) populates
    suggested_bar_id + similarity_score. Owner decides via the approval
    UI; the decision is captured on this row.

    Once accepted, the parent sync flow sets bar.slesh_negozio_id and
    future syncs find the bar by ID and never re-create this proposal.
    """
    __tablename__ = "slesh_shop_match_proposals"

    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Snapshot of the Slesh shop. We capture name at proposal time
    # so audit / display stays correct even if Slesh later renames it.
    slesh_shop_id:   Mapped[str] = mapped_column(String(64),  nullable=False)
    slesh_shop_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Best fuzzy-matched candidate. Nullable: there may be no bar above
    # threshold, in which case the owner must create a new bar or reject.
    suggested_bar_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("bars.id", ondelete="SET NULL"),
        nullable=True,
    )
    similarity_score: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, default=Decimal("0.000"),
    )

    # State machine. Pending -> accepted | rejected | skipped (terminal).
    status: Mapped[ShopMatchStatus] = mapped_column(
        Enum(ShopMatchStatus, name="shop_match_status", native_enum=True),
        nullable=False,
        default=ShopMatchStatus.PENDING,
    )

    # Decision audit. Both NULL while status=pending; both set on transition.
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Table-level invariants (also enforced in migration) ─────────────
    __table_args__ = (
        # Similarity always in [0, 1].
        CheckConstraint(
            "similarity_score >= 0 AND similarity_score <= 1",
            name="ck_slesh_shop_match_proposals_similarity_range",
        ),
        # decided_at is set iff status != pending. Prevents forgetting
        # to stamp the decision time on accept/reject/skip.
        CheckConstraint(
            "(status = \'PENDING\' AND decided_at IS NULL) "
            "OR (status != \'PENDING\' AND decided_at IS NOT NULL)",
            name="ck_slesh_shop_match_proposals_decided_at_consistent",
        ),
    )
