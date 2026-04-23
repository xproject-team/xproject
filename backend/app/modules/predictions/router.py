"""HTTP router for the Predictions module.

All endpoints are Owner-only (spec §10). Managers receive HTTP 403.
Enforcement happens via the `require_owner` dependency at the module level
— no endpoint in this router can be reached by a non-Owner user.

Mounted at /api/v1/predictions in app/main.py.

Contract reference: §1.1 (4-layer architecture), router layer owns:
  - HTTP dependency injection (tenant, user, role)
  - Input validation via Pydantic body models
  - Status code mapping from domain exceptions
  - Response envelope construction
Router NEVER touches DB or business logic — that's the service layer's job.

Spec: docs/predictions-module-spec.md §7.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User, UserRole
from app.modules.auth.router import get_current_user
from app.modules.predictions.schemas import (
    GeneratePredictionRequest,
    PredictionResponse,
    PredictionSummary,
    RegeneratePredictionRequest,
)
from app.modules.predictions.service import (
    PredictionGenerationError,
    PredictionNotFoundError,
    PredictionService,
)


# ─── Module-level dependency: Owner-only gate ────────────────────────────────
def require_owner(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Gate: raises 403 unless the caller's role is OWNER.

    Applied to every prediction endpoint via Depends(). Managers and other
    roles never see prediction data (spec §10 — predictions are Owner-only
    in v1.0; per-bar manager views ship in v1.2).
    """
    if current_user.role != UserRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "owner_only",
                "message": "Only the tenant Owner can access predictions.",
            },
        )
    return current_user


router = APIRouter()


# ─── GET /predictions/events/{event_id} — latest prediction for event ────────
# Ordered FIRST so /events/{event_id} doesn't get caught by /{prediction_id}.
@router.get("/events/{event_id}", response_model=PredictionResponse | None)
async def get_latest_prediction_for_event(
    event_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PredictionResponse | None:
    """Latest prediction version for this event, or null if never generated.

    Returns null (not 404) when no prediction exists. Frontend uses this
    to show the 'Generate Predictions' CTA vs. the populated page.
    """
    service = PredictionService(db)
    prediction = await service.get_latest_for_event(current_user.tenant_id, event_id)
    if prediction is None:
        return None
    return _response_from_prediction(prediction)


# ─── GET /predictions/events/{event_id}/history — all versions ────────────────
@router.get("/events/{event_id}/history", response_model=list[PredictionSummary])
async def list_prediction_history(
    event_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PredictionSummary]:
    """Full audit trail for a single event. Includes superseded versions."""
    service = PredictionService(db)
    predictions = await service.list_history(current_user.tenant_id, event_id)
    return [_summary_from_prediction(p) for p in predictions]


# ─── POST /predictions/generate — on-demand generation ───────────────────────
@router.post(
    "/generate",
    response_model=PredictionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_prediction(
    body: GeneratePredictionRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PredictionResponse:
    """On-demand generation. Idempotent: returns existing ready or
    insufficient_data prediction if one exists for (event, latest version).

    Status codes:
      201 — prediction generated (or returned from idempotent cache)
      404 — event does not exist in caller's tenant (wrapped by predictor)
      500 — predictor crashed (see server logs)

    Note: the response may have status='insufficient_data' with a message
    field populated. That's a VALID outcome (not an error), the UI renders
    a calm empty state from spec §3.1.
    """
    service = PredictionService(db)
    try:
        prediction = await service.generate_on_demand(
            tenant_id=current_user.tenant_id,
            event_id=body.event_id,
            generated_by=current_user.id,
        )
    except PredictionGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "generation_failed", "message": str(e)},
        )
    return _response_from_prediction(prediction)


# ─── GET /predictions/{prediction_id} — detail view ───────────────────────────
@router.get("/{prediction_id}", response_model=PredictionResponse)
async def get_prediction(
    prediction_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PredictionResponse:
    """Full PredictionResponse with inline PredictionData snapshot.

    404 if the prediction does not exist OR belongs to a different tenant.
    Tenant isolation is enforced at the service layer (repo.get_by_id
    filters by tenant_id).
    """
    service = PredictionService(db)
    try:
        prediction = await service.get_prediction(current_user.tenant_id, prediction_id)
    except PredictionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "prediction_not_found", "message": str(e)},
        )
    return _response_from_prediction(prediction)


# ─── POST /predictions/{prediction_id}/regenerate — admin, creates v+1 ───────
@router.post(
    "/{prediction_id}/regenerate",
    response_model=PredictionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def regenerate_prediction(
    prediction_id: UUID,
    body: RegeneratePredictionRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PredictionResponse:
    """Create a new version of an existing prediction.

    Sets old_prediction.superseded_by = new_prediction.id. The old row is
    NEVER deleted (audit trail sacrosanct).
    """
    service = PredictionService(db)
    try:
        prediction = await service.regenerate(
            tenant_id=current_user.tenant_id,
            prediction_id=prediction_id,
            generated_by=current_user.id,
        )
    except PredictionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "prediction_not_found", "message": str(e)},
        )
    except PredictionGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "generation_failed", "message": str(e)},
        )
    return _response_from_prediction(prediction)


# ─── Helpers: ORM → Pydantic converters ───────────────────────────────────────

def _summary_from_prediction(p) -> PredictionSummary:
    """Build a PredictionSummary from a Prediction ORM row."""
    event_name = p.event.name if p.event else "—"
    return PredictionSummary(
        id=p.id,
        event_id=p.event_id,
        event_name=event_name,
        version=p.version,
        status=p.status,
        predictor_type=p.predictor_type,
        confidence_tier=p.confidence_tier,
        based_on_event_count=p.based_on_event_count,
        generated_at=p.generated_at,
    )


def _response_from_prediction(p) -> PredictionResponse:
    """Build a PredictionResponse from a Prediction ORM row."""
    return PredictionResponse(
        id=p.id,
        event_id=p.event_id,
        version=p.version,
        superseded_by=p.superseded_by,
        status=p.status,
        predictor_type=p.predictor_type,
        confidence_tier=p.confidence_tier,
        based_on_event_count=p.based_on_event_count,
        generated_at=p.generated_at,
        data=p.data_json,
        insufficient_data_message=p.insufficient_data_message,
    )
