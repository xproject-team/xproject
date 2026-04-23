"""Business logic for the reports module — orchestrates report generation.

Contract reference: §1.1 (layered architecture), §1.5 (service owns transactions).

The service layer:
  1. Validates tenant scoping (never trusts router to filter by tenant).
  2. Enforces idempotency on on-demand generation (returns existing ready
     report instead of creating a duplicate).
  3. Orchestrates: repository.create → aggregator.aggregate → narrative.render
     → repository.mark_ready, all inside one transaction.
  4. Handles generation failures: catches exceptions from aggregator or
     narrative, marks the report row as `failed` with a reason, then
     re-raises so the caller (HTTP router or cron job) sees the error too.
  5. Owns the transaction boundary: repositories flush, services commit.
  6. Translates domain concerns into typed exceptions; router translates
     those into HTTP status codes.

Spec: docs/report-module-spec.md §5 + §7.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reports.aggregator import (
    EventNotCompletedError,
    EventNotFoundForReportError,
    ReportAggregator,
)
from app.modules.reports.models import Report
from app.modules.reports.narrative import render_narrative
from app.modules.reports.repository import ReportRepository
from app.modules.reports.schemas import PortfolioKpis


# ─── Domain exceptions ────────────────────────────────────────────────────────
# Router layer maps each to the appropriate HTTP status code.
# EventNotFoundForReportError + EventNotCompletedError already defined in
# aggregator.py; we just re-raise them.

class ReportNotFoundError(Exception):
    """Report does not exist OR belongs to a different tenant. Maps to 404."""


class ReportGenerationError(Exception):
    """Aggregator or narrative engine crashed during generation.
    The report row has been marked `failed` with a reason; caller gets 500.
    """


class ReportService:
    """All business logic for report operations.

    Services commit transactions. Repositories only flush. This lets one
    service call orchestrate multiple repo operations atomically.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ReportRepository(db)
        self.aggregator = ReportAggregator(db)

    # ─── Reads ────────────────────────────────────────────────────────────────

    async def get_report(self, tenant_id: UUID, report_id: UUID) -> Report:
        """Fetch a single report. Raises ReportNotFoundError if missing."""
        report = await self.repo.get_by_id(tenant_id, report_id)
        if report is None:
            raise ReportNotFoundError(f"Report {report_id} not found")
        return report

    async def get_report_in_language(
        self,
        tenant_id: UUID,
        report_id: UUID,
        language: str,
    ) -> Report:
        """Fetch a report, auto-creating the language sibling on demand.

        The frontend language toggle calls this. If the stored report is
        already in the requested language, returns it directly. Otherwise
        looks up the sibling (same event+version, different language).
        If the sibling doesn't exist, generates it inline using the same
        aggregator + narrative engine pipeline as generate_on_demand.

        Guarantees the UI can always render in EITHER language without
        asking the user to manually "Generate EN" as a separate action.
        """
        # First, the original so we know event_id + version to look up siblings
        original = await self.repo.get_by_id(tenant_id, report_id)
        if original is None:
            raise ReportNotFoundError(f"Report {report_id} not found")

        # Happy path: already in the right language
        if original.language == language:
            return original

        # Look for sibling with same (event, version) in the requested language
        siblings = await self.repo.list_for_event(tenant_id, original.event_id)
        for s in siblings:
            if s.version == original.version and s.language == language:
                return s

        # Sibling doesn't exist — generate it now.
        sibling = await self.repo.create(
            tenant_id=tenant_id,
            event_id=original.event_id,
            language=language,
            version=original.version,
            generated_by=original.generated_by,
        )
        return await self._populate_report(sibling)

    async def list_for_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> Sequence[Report]:
        """All report versions for an event, newest first."""
        return await self.repo.list_for_event(tenant_id, event_id)

    async def list_summaries(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        event_id: UUID | None = None,
        language: str | None = None,
        limit: int = 50,
    ) -> Sequence[Report]:
        """Paginated index-view list."""
        return await self.repo.list_summaries(
            tenant_id,
            status=status,
            event_id=event_id,
            language=language,
            limit=limit,
        )

    # ─── Portfolio KPIs (for /reports index-page top strip) ───────────────────

    async def get_portfolio_kpis(self, tenant_id: UUID) -> PortfolioKpis:
        """Assemble the 4-tile portfolio strip from 3 repo queries.

        v1.0: quarter/YoY deltas are set to safe defaults (0 / None) because
        we don't yet have enough events to compute meaningful comparisons.
        v1.1 will upgrade these once the data set justifies it.
        """
        total_events = await self.repo.count_completed_events_with_reports(tenant_id)
        lifetime_revenue = await self.repo.sum_lifetime_revenue(tenant_id)

        avg_event_revenue = (
            lifetime_revenue / Decimal(total_events)
            if total_events > 0
            else Decimal(0)
        )

        top_event = await self.repo.get_top_event_by_revenue(tenant_id)
        best_name = top_event[0] if top_event else None
        best_rev = top_event[1] if top_event else None

        return PortfolioKpis(
            total_events_completed=total_events,
            lifetime_revenue=lifetime_revenue,
            avg_event_revenue=avg_event_revenue,
            best_event_name=best_name,
            best_event_revenue=best_rev,
            events_delta_vs_last_quarter=0,
            revenue_delta_pct_yoy=None,
            avg_revenue_delta_vs_last_quarter=None,
        )

    # ─── Generation (on-demand) ───────────────────────────────────────────────

    async def generate_on_demand(
        self,
        tenant_id: UUID,
        event_id: UUID,
        language: str,
        generated_by: UUID | None = None,
    ) -> Report:
        """Create & generate a report on user request.

        Idempotency: if a `ready` report already exists for (event, latest
        version, language), returns it without creating a new row.

        Propagates EventNotFoundForReportError (→ 404) and
        EventNotCompletedError (→ 400) from the aggregator. If generation
        itself crashes, marks the row failed and raises ReportGenerationError.
        """
        existing = await self.repo.get_latest_for_event(tenant_id, event_id, language)
        if existing is not None and existing.status == "ready":
            return existing

        version = (existing.version + 1) if existing is not None else 1

        report = await self.repo.create(
            tenant_id=tenant_id,
            event_id=event_id,
            language=language,
            version=version,
            generated_by=generated_by,
        )

        return await self._populate_report(report)

    # ─── Generation (auto-trigger, both languages) ────────────────────────────

    async def generate_for_event_batch(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> list[Report]:
        """Generate IT + EN reports for an event. Called by the arq cron job.

        Generates sequentially. If one language fails, the other still gets
        attempted — we don't want an EN bug blocking Omar's Italian report.
        """
        results: list[Report] = []
        for language in ("it", "en"):
            try:
                # Skip if any version already exists (safety: cron shouldn't
                # re-trigger, but defense in depth)
                existing = await self.repo.get_latest_for_event(
                    tenant_id, event_id, language
                )
                if existing is not None:
                    results.append(existing)
                    continue

                report = await self.repo.create(
                    tenant_id=tenant_id,
                    event_id=event_id,
                    language=language,
                    version=1,
                    generated_by=None,  # NULL = auto-triggered
                )
                results.append(await self._populate_report(report))
            except Exception:
                # Language X failed — log and continue with the other one.
                # The failed row is already persisted via _populate_report.
                continue
        return results

    # ─── Regeneration (admin-only, creates v+1) ───────────────────────────────

    async def regenerate(
        self,
        tenant_id: UUID,
        report_id: UUID,
        *,
        language: str | None = None,
        generated_by: UUID | None = None,
    ) -> Report:
        """Create a new version of an existing report.

        Sets old_report.superseded_by = new_report.id. The old row is NEVER
        deleted — audit trail is sacrosanct.

        If `language` is omitted, inherits from the original. Useful when
        Omar wants to refresh just the Italian report without touching the
        English one.
        """
        old = await self.repo.get_by_id(tenant_id, report_id)
        if old is None:
            raise ReportNotFoundError(f"Report {report_id} not found")

        target_language = language or old.language
        new_version = old.version + 1

        new = await self.repo.create(
            tenant_id=tenant_id,
            event_id=old.event_id,
            language=target_language,
            version=new_version,
            generated_by=generated_by,
        )

        await self.repo.supersede(old, new.id)

        return await self._populate_report(new)

    # ─── Private: the generation pipeline ─────────────────────────────────────

    async def _populate_report(self, report: Report) -> Report:
        """Runs aggregator → narrative → mark_ready in one transaction.

        On failure: marks row as `failed` with a reason, commits (so the
        failure is durable), and re-raises as ReportGenerationError.
        EventNotFoundForReportError + EventNotCompletedError bypass this
        wrapper — they indicate a bad input, not a generation bug.
        """
        try:
            await self.repo.mark_generating(report)

            data = await self.aggregator.aggregate(
                tenant_id=report.tenant_id,
                event_id=report.event_id,
                report_id=report.id,
                version=report.version,
                language=report.language,
                generated_at=datetime.now(timezone.utc),
            )

            narrative = render_narrative(data, report.language)
            data.narrative = narrative

            # Pydantic v2 → dict for JSONB storage. mode='json' ensures
            # UUIDs and datetimes serialize as strings, not objects.
            data_json = data.model_dump(mode="json")

            await self.repo.mark_ready(
                report,
                data_json=data_json,
                pdf_bytes=None,  # Phase 2 will populate this
            )
            await self.db.commit()
            return report

        except (EventNotFoundForReportError, EventNotCompletedError):
            # Bad input — rollback the pending row creation, re-raise.
            await self.db.rollback()
            raise

        except Exception as exc:
            # Generation bug — persist the failure for diagnostics, then
            # surface to the caller as ReportGenerationError.
            await self.repo.mark_failed(report, reason=f"{type(exc).__name__}: {exc}")
            await self.db.commit()
            raise ReportGenerationError(
                f"Report generation failed for {report.id}: {exc}"
            ) from exc
