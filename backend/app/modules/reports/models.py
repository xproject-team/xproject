"""SQLAlchemy ORM models for the Reports module.

Reports are immutable post-event snapshots. Once a report reaches status='ready'
the data_json + pdf_bytes are frozen — any later correction creates a NEW row
with version+1 and the old row sets superseded_by = new.id. The old row is
NEVER deleted. This gives us a full audit trail forever.

Two hot queries dictate the index strategy:
  (tenant_id, event_id, version, language)    — UNIQUE; "get THE latest report"
  (tenant_id, event_id, status)               — "list reports for an event"
  (tenant_id, status, generated_at DESC)      — admin dashboards, cross-event

Inherits `id`, `tenant_id`, `created_at`, `updated_at` from TenantScopedModel.

Spec: docs/report-module-spec.md §4.1.
Migration: backend/alembic/versions/h1_add_reports.py.
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
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID as PgUUID
from sqlalchemy.orm import relationship

from app.core.tenancy import TenantScopedModel


# ─── Enums (native Postgres for type safety + efficient indexing) ─────────────
# create_type=False because the enums are declared explicitly in the migration
# (same pattern used by alerts, products, and every other domain module).
REPORT_STATUS_ENUM = SqlEnum(
    "pending",
    "generating",
    "ready",
    "failed",
    name="reportstatus",
    create_type=False,
)
REPORT_LANGUAGE_ENUM = SqlEnum(
    "it",
    "en",
    name="reportlanguage",
    create_type=False,
)


class Report(TenantScopedModel):
    """A post-event report snapshot.

    Three key invariants enforced in the service layer (not DB):
      - Immutability: once status='ready', data_json and pdf_bytes are never
        rewritten. Corrections spawn a new version.
      - Language pairing: on-demand generation creates ONE row per language;
        auto-trigger creates BOTH (it + en) in the same job batch.
      - No self-supersede: a report cannot point to itself via superseded_by.
        Enforced at DB level via the ck_reports_no_self_supersede CHECK.

    Inherits id (UUID PK), tenant_id (FK → tenants.id CASCADE), created_at,
    updated_at from TenantScopedModel.
    """

    __tablename__ = "reports"

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
        ForeignKey("reports.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Lifecycle state ─────────────────────────────────────────────────────
    status = Column(REPORT_STATUS_ENUM, nullable=False, default="pending")
    language = Column(REPORT_LANGUAGE_ENUM, nullable=False)

    # ── Payload (snapshot data + rendered PDF) ──────────────────────────────
    # data_json is the frozen ReportData (see schemas.py) — every number the
    # report ever claims, captured at generation time. pdf_bytes is populated
    # by Phase 2 (the PDF renderer); NULL until then.
    data_json = Column(JSONB, nullable=True)
    pdf_bytes = Column(BYTEA, nullable=True)

    # ── Audit fields ────────────────────────────────────────────────────────
    generated_at = Column(DateTime(timezone=True), nullable=True)
    generated_by = Column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    failure_reason = Column(Text, nullable=True)

    # ── Relationships ───────────────────────────────────────────────────────
    # String-based refs avoid import cycles; SQLAlchemy resolves them at
    # mapper-configuration time. No `tenant` relationship by codebase
    # convention — tenant_id is a scoping column, not a navigable ref.
    event = relationship("Event", foreign_keys=[event_id])
    generator = relationship("User", foreign_keys=[generated_by])
    supersedes = relationship(
        "Report",
        remote_side="Report.id",
        foreign_keys=[superseded_by],
        uselist=False,
    )

    # ── Table-level constraints & indexes ───────────────────────────────────
    # Mirror the migration exactly. SQLAlchemy reflection-in-CI will catch
    # drift between this and h1_add_reports.py.
    __table_args__ = (
        CheckConstraint(
            "superseded_by IS NULL OR id != superseded_by",
            name="ck_reports_no_self_supersede",
        ),
        Index(
            "ix_reports_tenant_event_version_language",
            "tenant_id",
            "event_id",
            "version",
            "language",
            unique=True,
        ),
        Index(
            "ix_reports_tenant_event_status",
            "tenant_id",
            "event_id",
            "status",
        ),
        Index(
            "ix_reports_tenant_status_generated_at",
            "tenant_id",
            "status",
            "generated_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Report {self.id} event={self.event_id} "
            f"v{self.version} {self.language} {self.status}>"
        )
