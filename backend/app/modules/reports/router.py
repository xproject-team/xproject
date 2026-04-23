"""HTTP router for the Reports module.

All endpoints are Owner-only (spec §10). Managers receive HTTP 403.
Enforcement happens via the `require_owner` dependency at the module level
— no endpoint in this router can be reached by a non-Owner user.

Mounted at /api/v1/reports in app/main.py; GET /events/{id}/reports lives
in the events router? — No: per spec §7 we expose it on this router via
the /events/{id}/reports path. Since main.py mounts us at /reports only,
the event-scoped list endpoint is actually served at
/api/v1/reports/events/{event_id} to stay within this module's prefix.
(Spec path updated — see §7 in docs/report-module-spec.md.)

Contract reference: §1.1 (4-layer architecture), router layer owns:
  - HTTP dependency injection (tenant, user, role)
  - Input validation via Pydantic body models
  - Status code mapping from domain exceptions
  - Response envelope construction
Router NEVER touches DB or business logic — that's the service layer's job.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User, UserRole
from app.modules.auth.router import get_current_user
from app.modules.reports.aggregator import (
    EventNotCompletedError,
    EventNotFoundForReportError,
)
from app.modules.reports.schemas import (
    GenerateReportRequest,
    PortfolioKpis,
    RegenerateReportRequest,
    ReportLanguage,
    ReportResponse,
    ReportStatus,
    ReportSummary,
)
from app.modules.reports.service import (
    ReportGenerationError,
    ReportNotFoundError,
    ReportService,
)


# ─── Module-level dependency: Owner-only gate ─────────────────────────────────
def require_owner(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Gate: raises 403 unless the caller's role is OWNER.

    Applied to every report endpoint via Depends(). Managers and other
    roles never see report data (spec §10 — reports are Owner-only).
    """
    if current_user.role != UserRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "owner_only",
                "message": "Only the tenant Owner can access reports.",
            },
        )
    return current_user


router = APIRouter()


# ─── GET /reports/portfolio/kpis ──────────────────────────────────────────────
# Ordered FIRST so /portfolio/kpis doesn't get caught by /{report_id} below.
@router.get("/portfolio/kpis", response_model=PortfolioKpis)
async def get_portfolio_kpis(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PortfolioKpis:
    """Cross-event KPIs for the /reports index-page top strip.

    Computes from the set of READY reports in IT language only (to avoid
    double-counting when IT+EN pairs exist). v1.0 returns safe defaults
    for quarter/YoY deltas until we have enough events to compare.
    """
    service = ReportService(db)
    return await service.get_portfolio_kpis(current_user.tenant_id)


# ─── GET /reports — paginated index ───────────────────────────────────────────
@router.get("", response_model=list[ReportSummary])
async def list_reports(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[ReportStatus | None, Query(alias="status")] = None,
    event_id: UUID | None = None,
    language: ReportLanguage | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ReportSummary]:
    """Paginated list of reports for the Reports index page.

    Each row enriches from the snapshot for list-card display (total_revenue,
    alerts_count, top_bar_name). Rows where status != 'ready' may have
    None for those fields.
    """
    service = ReportService(db)
    reports = await service.list_summaries(
        current_user.tenant_id,
        status=status_filter,
        event_id=event_id,
        language=language,
        limit=limit,
    )
    return [_summary_from_report(r) for r in reports]


# ─── GET /reports/events/{event_id} — all versions for one event ──────────────
@router.get("/events/{event_id}", response_model=list[ReportSummary])
async def list_reports_for_event(
    event_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ReportSummary]:
    """Full audit trail for a single event. Includes superseded versions.

    Used for the 'Past Reports' per-event detail view + diagnostic audits.
    """
    service = ReportService(db)
    reports = await service.list_for_event(current_user.tenant_id, event_id)
    return [_summary_from_report(r) for r in reports]


# ─── POST /reports/generate — on-demand generation ────────────────────────────
@router.post(
    "/generate",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_report(
    body: GenerateReportRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReportResponse:
    """On-demand generation. Idempotent: returns existing ready report if
    one exists for (event, latest version, language).

    Status codes:
      201 — report generated (or returned from idempotent cache)
      400 — event has no ended_at (not completed)
      404 — event does not exist in caller's tenant
      500 — aggregator or narrative crashed (see server logs)
    """
    service = ReportService(db)
    try:
        report = await service.generate_on_demand(
            tenant_id=current_user.tenant_id,
            event_id=body.event_id,
            language=body.language,
            generated_by=current_user.id,
        )
    except EventNotFoundForReportError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    except EventNotCompletedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "event_not_completed", "message": str(e)},
        )
    except ReportGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "generation_failed", "message": str(e)},
        )
    return _response_from_report(report)


# ─── GET /reports/{report_id} — detail view ───────────────────────────────────
@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReportResponse:
    """Full ReportResponse with inline ReportData snapshot.

    404 if the report does not exist OR belongs to a different tenant.
    Tenant isolation is enforced at the service layer (repo.get_by_id
    filters by tenant_id).
    """
    service = ReportService(db)
    try:
        report = await service.get_report(current_user.tenant_id, report_id)
    except ReportNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "report_not_found", "message": str(e)},
        )
    return _response_from_report(report)


# ─── GET /reports/{report_id}/pdf — raw PDF bytes ─────────────────────────────
@router.get("/{report_id}/pdf")
async def download_report_pdf(
    report_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Returns application/pdf bytes as an inline attachment.

    404 if the report doesn't exist.
    404 with 'pdf_not_yet_available' if the report exists but pdf_bytes
    is NULL (Phase 2 populates this; until then, all reports return 404
    for /pdf).
    """
    service = ReportService(db)
    try:
        report = await service.get_report(current_user.tenant_id, report_id)
    except ReportNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "report_not_found", "message": str(e)},
        )
    if report.pdf_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "pdf_not_yet_available",
                "message": "PDF generation is Phase 2 — not yet implemented.",
            },
        )
    filename = f"report-{report.event_id}-v{report.version}-{report.language}.pdf"
    return Response(
        content=bytes(report.pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ─── POST /reports/{report_id}/regenerate — admin re-gen, creates v+1 ─────────
@router.post(
    "/{report_id}/regenerate",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def regenerate_report(
    report_id: UUID,
    body: RegenerateReportRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReportResponse:
    """Create a new version of an existing report.

    Sets old_report.superseded_by = new_report.id. The old row is NEVER
    deleted (audit trail). If body.language is null, new version inherits
    the original's language.
    """
    service = ReportService(db)
    try:
        report = await service.regenerate(
            tenant_id=current_user.tenant_id,
            report_id=report_id,
            language=body.language,
            generated_by=current_user.id,
        )
    except ReportNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "report_not_found", "message": str(e)},
        )
    except EventNotFoundForReportError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    except EventNotCompletedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "event_not_completed", "message": str(e)},
        )
    except ReportGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "generation_failed", "message": str(e)},
        )
    return _response_from_report(report)


# ─── Helpers: ORM → Pydantic converters ──────────────────────────────────────
# Kept in the router because they're wire-format concerns. Service layer
# deals in ORM instances; router translates to response models.

def _summary_from_report(r) -> ReportSummary:
    """Build a ReportSummary from a Report ORM row + its eager-loaded event.

    Denormalizes revenue/alerts/top_bar from the JSON snapshot when the
    report is ready; leaves them None otherwise.
    """
    event = r.event  # selectinload()'d by list_summaries
    total_revenue = None
    alerts_count = None
    top_bar_name = None

    if r.status == "ready" and r.data_json:
        kpis = r.data_json.get("revenue_kpis") or {}
        total_revenue = kpis.get("total_revenue")
        alerts_count = len(r.data_json.get("alerts") or [])
        bar_revenues = r.data_json.get("bar_revenues") or []
        if bar_revenues:
            top_bar_name = bar_revenues[0].get("bar_name")

    return ReportSummary(
        id=r.id,
        event_id=r.event_id,
        event_name=event.name if event else "—",
        event_started_at=event.started_at if event else r.created_at,
        event_ended_at=event.ended_at if event else r.created_at,
        version=r.version,
        status=r.status,
        language=r.language,
        generated_at=r.generated_at,
        total_revenue=total_revenue,
        alerts_count=alerts_count,
        top_bar_name=top_bar_name,
    )


def _response_from_report(r) -> ReportResponse:
    """Build a ReportResponse from a Report ORM row."""
    return ReportResponse(
        id=r.id,
        event_id=r.event_id,
        version=r.version,
        superseded_by=r.superseded_by,
        status=r.status,
        language=r.language,
        generated_at=r.generated_at,
        data=r.data_json,  # raw dict; Pydantic validates → ReportData
    )
