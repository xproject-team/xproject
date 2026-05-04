"""HTTP router for the events module — input validation and response formatting only.

Contract reference: §1.1 (4-layer architecture), §6.1 (Events endpoints),
§7 (response conventions).

All business logic lives in the service layer. This file is thin on purpose:
parse request, call service, translate exceptions, return response.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timezone
from pydantic import BaseModel
from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.events.schemas import EventCreate, EventResponse, EventUpdate
from app.modules.events.service import (
    EventNotFoundError,
    EventService,
    LiveEventConflictError,
    StaleVersionError,
    VenueNotFoundError,
)
from app.modules.events.state_machine import (
    FieldLockedError,
    InvalidTransitionError,
)


# ─── Tenant resolver ──────────────────────────────────────────────────────────
# TODO(auth): once Clerk is wired, replace with Clerk-authenticated user lookup.

async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    """Return the authenticated user\'s tenant_id (from JWT claims)."""
    return current_user.tenant_id


# ─── Exception → HTTP translation ─────────────────────────────────────────────
# Single place where domain exceptions become HTTP responses.
# Keeps the endpoint functions clean and avoids scattered try/except blocks.

def _raise_http(exc: Exception) -> None:
    """Translate a known domain exception into an HTTPException.

    Contract §7.3 (error envelope): every error payload has at minimum
    error + message; some errors include extra context fields.
    """
    if isinstance(exc, EventNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(exc)},
        )
    if isinstance(exc, VenueNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "venue_not_found", "message": str(exc)},
        )
    if isinstance(exc, StaleVersionError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "stale_version",
                "message": str(exc),
                "current_version": exc.current_version,
            },
        )
    if isinstance(exc, LiveEventConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "event_already_live",
                "message": str(exc),
                "conflicting_event": {
                    "id": str(exc.conflicting_event.id),
                    "name": exc.conflicting_event.name,
                },
            },
        )
    if isinstance(exc, InvalidTransitionError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "invalid_transition",
                "message": str(exc),
                "from_status": exc.from_status.value,
                "to_status": exc.to_status.value,
            },
        )
    if isinstance(exc, FieldLockedError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "field_locked",
                "message": str(exc),
                "field": exc.field,
                "status": exc.status.value,
            },
        )
    raise exc  # unexpected — let FastAPI\'s default 500 handler deal with it


# ─── Router ───────────────────────────────────────────────────────────────────

router = APIRouter()


# ─── Reads ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[EventResponse])
async def list_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> list[EventResponse]:
    """List all events for the current tenant, newest first."""
    service = EventService(db)
    events = await service.list_events(tenant_id)
    responses = []
    for event in events:
        response_dict = await service.build_response_dict(event)
        responses.append(EventResponse.model_validate(response_dict))
    return responses


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventResponse:
    """Fetch a single event by ID. 404 if not found or wrong tenant."""
    service = EventService(db)
    try:
        event = await service.get_event(tenant_id, event_id)
    except EventNotFoundError as e:
        _raise_http(e)
    response_dict = await service.build_response_dict(event)
    return EventResponse.model_validate(response_dict)


# ─── Create ───────────────────────────────────────────────────────────────────

@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventResponse:
    """Create a new event (always status=draft). 404 if venue invalid."""
    service = EventService(db)
    try:
        event = await service.create_event(tenant_id, payload)
    except VenueNotFoundError as e:
        _raise_http(e)
    response_dict = await service.build_response_dict(event)
    return EventResponse.model_validate(response_dict)


# ─── Update ───────────────────────────────────────────────────────────────────

@router.patch("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: UUID,
    payload: EventUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventResponse:
    """Update an event\'s editable fields.

    Requires `version` in the body (optimistic locking, contract §4).
    Returns 409 if version is stale OR if any field is locked in the
    current status (e.g. changing venue on a Live event).
    """
    service = EventService(db)
    try:
        event = await service.update_event(tenant_id, event_id, payload)
    except (
        EventNotFoundError, VenueNotFoundError,
        StaleVersionError, FieldLockedError,
    ) as e:
        _raise_http(e)
    response_dict = await service.build_response_dict(event)
    return EventResponse.model_validate(response_dict)


# ─── Delete ───────────────────────────────────────────────────────────────────

@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> Response:
    """Delete a DRAFT event (children CASCADE). 409 for non-Draft statuses."""
    service = EventService(db)
    try:
        await service.delete_event(tenant_id, event_id)
    except (EventNotFoundError, InvalidTransitionError) as e:
        _raise_http(e)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── Status transitions ───────────────────────────────────────────────────────

@router.post("/{event_id}/activate", response_model=EventResponse)
async def activate_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventResponse:
    """Transition DRAFT → ACTIVE. Idempotent: calling on Active is a no-op."""
    service = EventService(db)
    try:
        event = await service.activate_event(tenant_id, event_id)
    except (EventNotFoundError, InvalidTransitionError) as e:
        _raise_http(e)
    response_dict = await service.build_response_dict(event)
    return EventResponse.model_validate(response_dict)


@router.post("/{event_id}/start", response_model=EventResponse)
async def start_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventResponse:
    """Transition ACTIVE → LIVE.

    Enforces one-live-per-tenant invariant with auto-end-if-stale logic
    (contract Q1 hybrid). Returns 409 with conflicting_event info if
    another event is genuinely live.
    """
    service = EventService(db)
    try:
        event = await service.start_event(tenant_id, event_id)
    except (
        EventNotFoundError, InvalidTransitionError, LiveEventConflictError,
    ) as e:
        _raise_http(e)
    response_dict = await service.build_response_dict(event)
    return EventResponse.model_validate(response_dict)


@router.post("/{event_id}/end", response_model=EventResponse)
async def end_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventResponse:
    """Transition LIVE → COMPLETED. Idempotent."""
    service = EventService(db)
    try:
        event = await service.end_event(tenant_id, event_id)
    except (EventNotFoundError, InvalidTransitionError) as e:
        _raise_http(e)
    response_dict = await service.build_response_dict(event)
    return EventResponse.model_validate(response_dict)



# ─── Weather (B.10) ───────────────────────────────────────────────────────────
class EventWeatherResponse(BaseModel):
    """Slim shape for the dashboard weather pill + post-event reports.

    `snapshot` is the raw Open-Meteo response (JSONB column dumped as-is)
    when present, or None if the weather sync has not run for this event.
    The frontend reads `snapshot.current` for the pill and `snapshot.hourly`
    for the upcoming-hours strip.
    """
    event_id:           UUID
    weather_fetched_at: datetime | None = None
    snapshot:           dict | None      = None
    is_stale:           bool             = False    # >2h since fetch


@router.get("/{event_id}/weather", response_model=EventWeatherResponse)
async def get_event_weather(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventWeatherResponse:
    """Return the most recent weather snapshot persisted on the event row.

    Behavior:
      - 404 if the event does not exist for this tenant.
      - 200 with snapshot=None if the event exists but weather was never synced.
      - 200 with the full snapshot otherwise.
    """
    service = EventService(db)
    try:
        event = await service.get_event(tenant_id, event_id)
    except EventNotFoundError as e:
        _raise_http(e)

    is_stale = False
    if event.weather_fetched_at is not None:
        age = datetime.now(tz=timezone.utc) - event.weather_fetched_at
        is_stale = age.total_seconds() > 7200    # 2 hours

    return EventWeatherResponse(
        event_id           = event.id,
        weather_fetched_at = event.weather_fetched_at,
        snapshot           = event.weather_snapshot,
        is_stale           = is_stale,
    )
