"""SQLAlchemy ORM models for the Alerts module.

Alerts are the product's core signal: early warnings so the Owner discovers
operational problems before they become painful. The table is append-only in
spirit — rows are never deleted during an event. Lifecycle transitions
(acknowledge, auto-resolve, expire) are captured as timestamps so the
post-event report can reconstruct the full narrative of what happened and
who acted on it.

Multi-tenant, multi-event. Indexed for the two hot queries:
  (tenant_id, event_id, created_at)            — "what's active right now?"
  (tenant_id, event_id, bar_id, product_id,    — dedup key
   alert_type)
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Enum as SqlEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


# ─── Enums (native Postgres for type safety + efficient indexing) ─────────────
# create_type=False because the enums are declared explicitly in the migration
# (matches the pattern we use for product_type, product_category, product_unit).

ALERT_TYPE_ENUM = SqlEnum(
    "depletion",
    "anomaly",
    "discrepancy",
    "system",
    name="alert_type",
    create_type=False,
)

ALERT_SEVERITY_ENUM = SqlEnum(
    "info",
    "warning",
    "critical",
    "anomaly",
    name="alert_severity",
    create_type=False,
)

ALERT_AUDIENCE_ENUM = SqlEnum(
    "owner_only",
    "owner_and_manager",
    name="alert_audience",
    create_type=False,
)


class Alert(Base):
    """An alert fired by the evaluation engine.

    Two key invariants enforced in the service layer (not DB):
    - Deduplication: (tenant, event, bar, product, alert_type) has at most ONE
      active (unacknowledged + unresolved + unexpired) row at a time.
    - Immutability of core fields: once fired, alert_type/severity/audience
      never change. Escalation = new alert, old one auto-resolved.
    """
    __tablename__ = "alerts"

    # ── Identity & tenancy ──────────────────────────────────────────────────
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── Scope: which event, which bar, optionally which product ────────────
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Nullable (migration aa9, Jul-19 sprint): "unmapped Slesh shop"
    # alerts (alert_type='system', context_json.category='unmapped_shop')
    # have no bar by definition — that's the whole condition being
    # reported. Every other alert type still always sets this.
    bar_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bars.id", ondelete="CASCADE"),
        nullable=True,
    )
    # product_id is nullable: bar-level anomalies (e.g. revenue shortfall)
    # do not apply to a specific product. SET NULL on product delete so we
    # don't lose alert history when a product gets archived later.
    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Classification ─────────────────────────────────────────────────────
    alert_type = Column(ALERT_TYPE_ENUM, nullable=False)
    severity = Column(ALERT_SEVERITY_ENUM, nullable=False)
    audience = Column(ALERT_AUDIENCE_ENUM, nullable=False)

    # ── Display content ────────────────────────────────────────────────────
    # Short headline. e.g. "Bacardi Rum running low"
    title = Column(String(160), nullable=False)
    # Detailed explanation for the Owner. Contains numbers, context, the WHY.
    owner_message = Column(Text, nullable=False)
    # Sanitized text for the Manager. Operational only. NEVER shown to Owner.
    # NULL when audience = owner_only (anomaly alerts, by design).
    manager_message = Column(Text, nullable=True)
    # What the Owner should do. Rule-based strings today; AI-generated
    # reasoning slot tomorrow. Same schema, richer content.
    suggested_action = Column(Text, nullable=True)
    # Reserved for a future LLM advisor that enriches suggested_action with
    # historical reasoning ("last Sundance Bar 3 ran out at 21:00..."). The
    # frontend already reads this slot if populated; keeps the upgrade path
    # free of schema churn.
    ai_advisory = Column(Text, nullable=True)

    # ── Detector-specific context (JSONB for extensibility) ────────────────
    # Depletion: {current_stock, burn_rate_per_hour, ttd_minutes, window_label}
    # Revenue anomaly: {predicted_cents, actual_cents, pct_deviation}
    # Consumption ratio: {expected_qty, actual_qty, ratio}
    # Each detector documents its own context shape in its module.
    context_json = Column(JSONB, nullable=False, default=dict)

    # ── Lifecycle timestamps (the narrative source for reports) ────────────
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now().astimezone(),
    )
    # When the Owner clicked Acknowledge. NULL = still active, needs attention.
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # When the underlying condition stopped applying (e.g. stock was restocked
    # and time-to-depletion rose above the INFO threshold). System resolved
    # it; Owner didn't need to act.
    auto_resolved_at = Column(DateTime(timezone=True), nullable=True)
    # When a human explicitly marked this resolved (migration ag1) — distinct
    # from auto_resolved_at (system-detected) and from acknowledged_at
    # (Owner has seen it, not necessarily that it's over). Covers the case
    # where the underlying condition was fixed OUTSIDE the platform (e.g. a
    # Slesh shop mapping corrected via direct DB work) and no detector will
    # ever naturally clear it.
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # When the event ended while the alert was still unacknowledged and
    # unresolved. "Timed out" — Owner never got to it. Key signal for report:
    # "3 alerts fired during the event that you never acknowledged."
    expired_at = Column(DateTime(timezone=True), nullable=True)

    # ── Concurrency ────────────────────────────────────────────────────────
    # Optimistic locking for acknowledge: if two Owner tabs try to ack the
    # same alert simultaneously, the stale one gets a 409 and must refetch.
    # Same pattern used in Events module.
    version = Column(Integer, nullable=False, default=1)

    # ── ORM relationships (lazy, only loaded on demand) ────────────────────
    acknowledged_by = relationship("User", foreign_keys=[acknowledged_by_user_id])
    resolved_by = relationship("User", foreign_keys=[resolved_by_user_id])
    event = relationship("Event", foreign_keys=[event_id])
    bar = relationship("Bar", foreign_keys=[bar_id])
    product = relationship("Product", foreign_keys=[product_id])

    # ── Indexes ────────────────────────────────────────────────────────────
    # Query #1 (hot): "What's active for this event right now?" — sidebar,
    #                 AlertsPage, top-bar counter.
    # Query #2 (dedup): Before creating a new alert, look up by the dedup key.
    # Query #3 (drill-down): Per-bar alert list for BarDetailOverlay.
    __table_args__ = (
        Index(
            "ix_alerts_tenant_event_active",
            "tenant_id",
            "event_id",
            "created_at",
        ),
        Index(
            "ix_alerts_dedup_key",
            "tenant_id",
            "event_id",
            "bar_id",
            "product_id",
            "alert_type",
        ),
        Index(
            "ix_alerts_tenant_event_bar",
            "tenant_id",
            "event_id",
            "bar_id",
        ),
    )

    # ── Computed helpers ───────────────────────────────────────────────────
    @property
    def is_active(self) -> bool:
        """True iff no lifecycle timestamp has fired — the alert still
        needs attention. Used by service-layer ergonomics and tests; the
        hot query path uses explicit WHERE conditions for index usage."""
        return (
            self.acknowledged_at is None
            and self.auto_resolved_at is None
            and self.resolved_at is None
            and self.expired_at is None
        )

    @property
    def lifecycle_state(self) -> str:
        """One-word state for the frontend + the report generator.
        Order matters: expiration and resolution can coexist with an ack
        (e.g. Owner acked, then system resolved). We surface the most
        informative state."""
        if self.expired_at is not None:
            return "expired"
        if self.resolved_at is not None:
            return "resolved"
        if self.auto_resolved_at is not None:
            return "auto_resolved"
        if self.acknowledged_at is not None:
            return "acknowledged"
        return "active"

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Alert id={self.id} type={self.alert_type} "
            f"severity={self.severity} state={self.lifecycle_state}>"
        )