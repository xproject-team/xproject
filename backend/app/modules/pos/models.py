"""SQLAlchemy ORM models for the pos module.

Currently contains:
  - SleshShopMatchProposal: pending name-matching decisions between
    Slesh shop IDs and existing bars. Owner approves/rejects each
    before the linkage is persisted on the bar. Populated by the
    HOURLY sync_shops() cron, matching Slesh's shop *list* against
    unlinked bars by fuzzy name.
  - PendingShopMapping: real-time defensive fix (Jul-19 sprint). Parks
    orders for an unmapped shop_id the moment an *order* arrives for
    it — catches a shop coming online mid-event, before the next
    hourly sync tick would. A separate, deliberately non-overlapping
    system from SleshShopMatchProposal — see PendingShopMapping's
    docstring for why they aren't merged.

See docs/e2e-validation-design.md (S4 — Name-matching UX).
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
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


# ─── Phantom-bar defensive fix (Jul-19 sprint) ─────────────────────────────────

class PendingShopMapping(TenantScopedModel):
    """An unmapped Slesh shop_id parked by the real-time order ingester.

    Root cause of the Sundance Jul-5 phantom-bar incidents: three food
    trucks came online mid-event with no bar.slesh_negozio_id set. The
    first order from each caused order_ingester._resolve_bar to
    silently auto-create a phantom bar (see order_ingester.py). This
    table is the fix: when an order arrives for a shop_id with no
    matching bar, the ingester parks it here (see
    pending_shop_mappings_service._park_unmapped_order) instead of
    creating a bar, and fires a WARNING alert (alert_type='system',
    context_json.category='unmapped_shop') via the alerts
    infrastructure so the Owner sees it without SSH.

    Resolution: POST /events/{event_id}/pending-shop-mappings/{id}/resolve
    sets the target bar's slesh_negozio_id, marks this row resolved, and
    replays every parked order through the normal ingest_order() path —
    same recipe cascade, same idempotency guarantees as a live order.

    Distinct from SleshShopMatchProposal (this same module): that one is
    populated by the HOURLY sync_shops() cron comparing Slesh's shop
    *list* against unlinked bars via fuzzy name match — proactive, but
    too slow to catch a food truck's first order mid-event. This one
    fires in real time, at the moment of the order itself. Both are
    kept as separate systems deliberately (not merged) — see the Jul-19
    sprint discovery notes.
    """
    __tablename__ = "pending_shop_mappings"

    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )

    slesh_shop_id: Mapped[str] = mapped_column(String(128), nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    order_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )
    total_gross_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    sample_operator_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )

    # Raw Slesh Order payloads (pydantic Order.model_dump(by_alias=True)),
    # one per parked order — round-tripped via Order.model_validate() and
    # replayed through ingest_order() on resolve. See migration aa8's
    # docstring for why this column exists beyond the literal spec.
    parked_orders_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    resolved_bar_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("bars.id", ondelete="SET NULL"),
        nullable=True,
    )
