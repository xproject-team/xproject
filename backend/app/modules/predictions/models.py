"""SQLAlchemy ORM models for the Predictions module.

Predictions are immutable post-generation snapshots. Once a prediction reaches
status='ready' the data_json is frozen — any later regeneration creates a NEW
row with version+1 and the old row sets superseded_by = new.id. The old row
is NEVER deleted. This gives us a full audit trail and lets Model C (Track 2)
compare prediction-vs-actual across versions.

Three hot queries dictate the index strategy:
  (tenant_id, event_id, version)          — UNIQUE; "get THE latest prediction"
  (tenant_id, event_id, status)           — "list predictions for an event"
  (tenant_id, status, generated_at DESC)  — admin dashboards, cross-event

Inherits id, tenant_id, created_at, updated_at from TenantScopedModel.

Spec: docs/predictions-module-spec.md §4.1.
Migration: backend/alembic/versions/i1_add_predictions.py.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    Enum as SqlEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import relationship

from app.core.tenancy import TenantScopedModel


# ─── Enums (native Postgres for type safety + efficient indexing) ─────────────
# create_type=False because the enums are declared explicitly in the migration
# (same pattern used by reports, alerts, and every other domain module).
PREDICTION_STATUS_ENUM = SqlEnum(
    "pending",
    "generating",
    "ready",
    "failed",
    "insufficient_data",
    name="predictionstatus",
    create_type=False,
)
PREDICTOR_TYPE_ENUM = SqlEnum(
    "heuristic",
    "ml",
    name="predictortype",
    create_type=False,
)
CONFIDENCE_TIER_ENUM = SqlEnum(
    "low",
    "medium",
    "high",
    name="confidencetier",
    create_type=False,
)


class Prediction(TenantScopedModel):
    """A demand prediction snapshot.

    Three key invariants enforced in the service layer (not DB):
      - Immutability: once status='ready' or status='insufficient_data',
        data_json is never rewritten. Corrections spawn a new version.
      - Predictor monotonicity: once we switch from heuristic to ml for
        a given tenant, we do NOT switch back. ml predictions supersede
        heuristic ones for the same (event, version) pair only if explicitly
        regenerated.
      - No self-supersede: a prediction cannot point to itself via
        superseded_by. Enforced at DB level via
        ck_predictions_no_self_supersede CHECK.

    Inherits id (UUID PK), tenant_id (FK → tenants.id CASCADE), created_at,
    updated_at from TenantScopedModel.
    """

    __tablename__ = "predictions"

    # ── Foreign keys to other domains ───────────────────────────────────────
    event_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── Versioning (for regeneration audit trail) ───────────────────────────
    version = Column(Integer, nullable=False, default=1)
    superseded_by = Column(
        PgUUID(as_uuid=True),
        ForeignKey("predictions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Lifecycle state ─────────────────────────────────────────────────────
    status = Column(PREDICTION_STATUS_ENUM, nullable=False, default="pending")
    predictor_type = Column(
        PREDICTOR_TYPE_ENUM, nullable=False, default="heuristic",
    )

    # ── Payload (the frozen prediction snapshot) ────────────────────────────
    # data_json is the frozen PredictionData (see schemas.py) — every number
    # the prediction ever claims, captured at generation time. NULL while
    # status in (pending, generating, insufficient_data, failed).
    data_json = Column(JSONB, nullable=True)

    # ── Metadata about the prediction quality ───────────────────────────────
    based_on_event_count = Column(Integer, nullable=False, default=0)
    confidence_tier = Column(
        CONFIDENCE_TIER_ENUM, nullable=False, default="low",
    )

    # ── Audit fields ────────────────────────────────────────────────────────
    generated_at = Column(DateTime(timezone=True), nullable=True)
    generated_by = Column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    failure_reason = Column(Text, nullable=True)
    insufficient_data_message = Column(Text, nullable=True)

    # ── Relationships ───────────────────────────────────────────────────────
    # String-based refs avoid import cycles; SQLAlchemy resolves them at
    # mapper-configuration time. No `tenant` relationship by codebase
    # convention — tenant_id is a scoping column, not a navigable ref.
    event = relationship("Event", foreign_keys=[event_id])
    generator = relationship("User", foreign_keys=[generated_by])
    supersedes = relationship(
        "Prediction",
        remote_side="Prediction.id",
        foreign_keys=[superseded_by],
        uselist=False,
    )

    # ── Table-level constraints & indexes ───────────────────────────────────
    # Mirror the migration exactly. SQLAlchemy reflection-in-CI will catch
    # drift between this and i1_add_predictions.py.
    __table_args__ = (
        CheckConstraint(
            "superseded_by IS NULL OR id != superseded_by",
            name="ck_predictions_no_self_supersede",
        ),
        Index(
            "ix_predictions_tenant_event_version",
            "tenant_id",
            "event_id",
            "version",
            unique=True,
        ),
        Index(
            "ix_predictions_tenant_event_status",
            "tenant_id",
            "event_id",
            "status",
        ),
        Index(
            "ix_predictions_tenant_status_generated_at",
            "tenant_id",
            "status",
            "generated_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Prediction {self.id} event={self.event_id} "
            f"v{self.version} {self.predictor_type} {self.status}>"
        )
