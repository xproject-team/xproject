"""Database queries for the reports module — pure data access, no business logic.

This file owns ALL SQL for the reports domain. Services never write SQL.
Transaction boundaries are OWNED BY SERVICES — every method here flushes
but NEVER commits.

Spec: docs/report-module-spec.md §4 + §5.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import and_, desc, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.customer_analytics.models import CustomerSession
from app.modules.events.models import Event, EventStatus
from app.modules.reports.models import Report


class ReportRepository:
    """Handles all SQL operations for Report records.

    Tenant isolation is NON-NEGOTIABLE — every public method takes tenant_id
    as the first argument and filters at SQL level. A missing tenant_id filter
    is a security bug; reviewers should fail the PR.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Reads ────────────────────────────────────────────────────────────────

    async def get_by_id(
        self,
        tenant_id: UUID,
        report_id: UUID,
    ) -> Report | None:
        """Fetch a single report by ID, scoped to tenant.

        Returns None if not found OR if the report belongs to a different tenant.
        """
        stmt = (
            select(Report)
            .where(
                Report.tenant_id == tenant_id,
                Report.id == report_id,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
        language: str,
    ) -> Report | None:
        """Return the highest-version report for (tenant, event, language).

        Used by the on-demand generation path for idempotency: if the latest
        version is already `ready`, POST /reports/generate returns it instead
        of creating a duplicate row.
        """
        stmt = (
            select(Report)
            .where(
                Report.tenant_id == tenant_id,
                Report.event_id == event_id,
                Report.language == language,
            )
            .order_by(Report.version.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_max_version_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> int:
        """Highest version number used by ANY report row for this event —
        every language, every status (failed rows hold their slot on the
        unique (tenant, event, version, language) index too).

        Used by regenerate() to allocate event-scoped version numbers:
        language version sequences can diverge (observed in production —
        e.g. latest IT at v1 while EN is at v2), and a per-language
        allocation then lands a regenerated report on a version whose
        sibling slot in the OTHER language is already occupied by an
        older snapshot. The language-sibling pairing is by (version,
        language), so a regenerated version must be free in every
        language. Returns 0 if the event has no reports.
        """
        stmt = (
            select(func.coalesce(func.max(Report.version), 0))
            .where(
                Report.tenant_id == tenant_id,
                Report.event_id == event_id,
            )
        )
        return int((await self.db.execute(stmt)).scalar_one())

    async def list_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> Sequence[Report]:
        """All report versions for an event, both languages, newest first.

        Powers GET /events/{event_id}/reports — shows the full audit trail
        including superseded versions.
        """
        stmt = (
            select(Report)
            .where(
                Report.tenant_id == tenant_id,
                Report.event_id == event_id,
            )
            .order_by(Report.version.desc(), Report.language)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_summaries(
        self,
        tenant_id: UUID,
        status: str | None = None,
        event_id: UUID | None = None,
        language: str | None = None,
        limit: int = 50,
    ) -> Sequence[Report]:
        """Paginated index-view query, newest generation first.

        Powers GET /reports. Eager-loads the related event for ReportSummary
        denormalization (event_name, event_started_at, event_ended_at).
        """
        stmt = (
            select(Report)
            .options(selectinload(Report.event))
            .where(Report.tenant_id == tenant_id)
            .order_by(desc(Report.created_at))
            .limit(limit)
        )
        if status is not None:
            stmt = stmt.where(Report.status == status)
        if event_id is not None:
            stmt = stmt.where(Report.event_id == event_id)
        if language is not None:
            stmt = stmt.where(Report.language == language)

        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_events_needing_reports(
        self,
        grace_minutes: int = 15,
        force_after_minutes: int = 30,
    ) -> Sequence[Event]:
        """Events whose auto-trigger window has elapsed and have no report yet.

        Called by the arq cron job. Cross-tenant scan is intentional — the
        cron runs in system context, not user context, because report
        generation is a system-initiated side-effect of event completion.

        An event is "due" when:
          - status = COMPLETED
          - ended_at is not null AND ended_at < (now - grace_minutes)
          - NOT EXISTS any report row for this event (any language, any version)
          - AND (customer_sessions exist for this event OR ended_at < now - force_after_minutes)

        That last condition is the ordering guarantee for the Guests/
        Comparison/Decomposition report sections, which read
        customer_sessions/customer_purchases (populated by a separate
        arq job enqueued at the same end_event() moment — see
        EventService._enqueue_customer_features_population). Between
        grace_minutes and force_after_minutes, an event whose population
        job hasn't finished yet is simply not returned this tick — the
        next tick (5 min later) checks again, so a slow population job
        gets retried "for free" by the existing cron cadence, no new
        infrastructure needed. Past force_after_minutes the report
        generates regardless, with those sections gracefully degraded —
        this is a hard cutoff, not an optional nicety: a stuck/failed
        population job must never permanently block a report.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=grace_minutes)
        force_cutoff = datetime.now(timezone.utc) - timedelta(minutes=force_after_minutes)
        population_ready = exists().where(
            CustomerSession.tenant_id == Event.tenant_id,
            CustomerSession.event_id == Event.id,
        )
        stmt = (
            select(Event)
            .where(
                Event.status == EventStatus.COMPLETED,
                Event.ended_at.is_not(None),
                Event.ended_at < cutoff,
                ~exists().where(Report.event_id == Event.id),
                sa.or_(population_ready, Event.ended_at < force_cutoff),
            )
            .order_by(Event.ended_at.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    # ─── Writes (pending/generating/ready/failed lifecycle) ───────────────────

    async def create(
        self,
        tenant_id: UUID,
        event_id: UUID,
        language: str,
        version: int = 1,
        generated_by: UUID | None = None,
    ) -> Report:
        """Insert a new report row with status=pending.

        Service layer is responsible for resolving the correct `version` —
        typically 1 for first generation, or previous.version+1 for regenerate.
        Flushes to assign id + populate server-side defaults. Does NOT commit.
        """
        report = Report(
            tenant_id=tenant_id,
            event_id=event_id,
            language=language,
            version=version,
            status="pending",
            generated_by=generated_by,
        )
        self.db.add(report)
        await self.db.flush()
        await self.db.refresh(report)
        return report

    async def mark_generating(self, report: Report) -> Report:
        """Transition pending → generating. Flushes but does not commit."""
        report.status = "generating"
        await self.db.flush()
        await self.db.refresh(report)
        return report

    async def mark_ready(
        self,
        report: Report,
        data_json: dict,
        pdf_bytes: bytes | None = None,
    ) -> Report:
        """Transition generating → ready, writes the frozen snapshot.

        `pdf_bytes` is optional because the PDF renderer ships in Phase 2 —
        until then, ready reports have data_json but no PDF, and GET
        /reports/{id}/pdf returns 404 until pdf_bytes is populated.
        Flushes but does not commit.
        """
        report.status = "ready"
        report.data_json = data_json
        report.pdf_bytes = pdf_bytes
        report.generated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(report)
        return report

    async def mark_failed(
        self,
        report: Report,
        reason: str,
    ) -> Report:
        """Transition * → failed with a human-readable reason.

        No auto-retry — next cron tick will skip this event because a row
        (even failed) exists. Manual retry via POST /reports/{id}/regenerate
        creates a NEW row with version+1.
        Flushes but does not commit.
        """
        report.status = "failed"
        report.failure_reason = reason
        await self.db.flush()
        await self.db.refresh(report)
        return report

    async def supersede(self, old_report: Report, new_report_id: UUID) -> Report:
        """Point old_report.superseded_by at new_report_id.

        Called during regeneration AFTER the new row is created but BEFORE
        we enqueue its generation job. The old row's status is unchanged —
        it remains in whatever terminal state it reached (ready/failed).
        The CHECK constraint ck_reports_no_self_supersede prevents any
        accidental self-reference.
        Flushes but does not commit.
        """
        old_report.superseded_by = new_report_id
        await self.db.flush()
        await self.db.refresh(old_report)
        return old_report

    # ─── Aggregates (for PortfolioKpis on /reports index page) ────────────────

    async def count_completed_events_with_reports(self, tenant_id: UUID) -> int:
        """Distinct count of events that have at least one ready report."""
        stmt = (
            select(func.count(func.distinct(Report.event_id)))
            .where(
                Report.tenant_id == tenant_id,
                Report.status == "ready",
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one() or 0

    def _latest_ready_it_reports_subquery(self, tenant_id: UUID):
        """Subquery: ONE row per event — its latest ready IT report.

        Every cross-report aggregate must go through this: regeneration
        leaves the superseded version at status='ready' too, so summing
        or averaging over all ready rows double-counts every regenerated
        event (C2, Day 14 audit). DISTINCT ON (event_id) ordered by
        version DESC picks the newest ready snapshot per event.
        """
        revenue_text = Report.data_json["revenue_kpis"]["total_revenue"].astext
        revenue_numeric = func.cast(revenue_text, sa.Numeric(14, 2))
        event_name = Report.data_json["event"]["event_name"].astext
        return (
            select(
                Report.event_id.label("event_id"),
                event_name.label("event_name"),
                revenue_numeric.label("revenue"),
            )
            .where(
                Report.tenant_id == tenant_id,
                Report.status == "ready",
                Report.language == "it",  # avoid double-counting IT+EN pairs
            )
            .distinct(Report.event_id)
            .order_by(Report.event_id, Report.version.desc())
            .subquery()
        )

    async def sum_lifetime_revenue(self, tenant_id: UUID) -> Decimal:
        """Sum of total_revenue across events' latest ready reports.

        Revenue lives in data_json['revenue_kpis']['total_revenue']. We use
        Postgres JSONB extraction rather than hydrating every row, because
        this runs on every index-page load. One figure per event — see
        _latest_ready_it_reports_subquery.
        Returns Decimal(0) if no reports exist yet.
        """
        latest = self._latest_ready_it_reports_subquery(tenant_id)
        stmt = select(func.coalesce(func.sum(latest.c.revenue), 0))
        result = await self.db.execute(stmt)
        value = result.scalar_one()
        return Decimal(str(value)) if value is not None else Decimal(0)

    async def get_top_event_by_revenue(
        self,
        tenant_id: UUID,
    ) -> tuple[str, Decimal] | None:
        """Highest-revenue completed event: (event_name, revenue) or None.

        Joins through data_json — same reason as sum_lifetime_revenue, and
        the same one-figure-per-event rule: a superseded version's stale
        number must never win the "Best Event" tile.
        """
        latest = self._latest_ready_it_reports_subquery(tenant_id)
        stmt = (
            select(latest.c.event_name, latest.c.revenue)
            .order_by(desc(latest.c.revenue))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        row = result.first()
        if row is None:
            return None
        return (row[0], Decimal(str(row[1])))
