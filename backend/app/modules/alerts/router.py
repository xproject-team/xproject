"""HTTP + WebSocket router for the Alerts module.

Endpoints:
    GET   /alerts/by-event/{event_id}              list alerts (role-filtered)
    GET   /alerts/by-event/{event_id}/count        {severity: count} for top bar
    GET   /alerts/by-event/{event_id}/count-by-bar {bar: {severity: count}}
    GET   /alerts/{alert_id}                        single alert detail
    PATCH /alerts/{alert_id}/acknowledge            optimistic-lock ack

    WS    /ws/alerts/{event_id}                     live push (stub, wired in 1.8)

Role enforcement is delegated to AlertsService (single source of truth).
Managers only ever see alerts for their own bar with audience='owner_and_manager'.
Anomaly alerts never reach managers by construction (service filter).
"""
from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.alerts.schemas import (
    AlertAcknowledge,
    AlertAcknowledgeResponse,
    AlertListResponse,
    AlertResponse,
)
from app.modules.alerts.service import (
    AlertAccessDeniedError,
    AlertAlreadyAcknowledgedError,
    AlertNotFoundError,
    AlertsService,
    StaleAlertVersionError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Dependencies ─────────────────────────────────────────────────────────────


async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return current_user.tenant_id


# ─── GET /alerts/by-event/{event_id} ──────────────────────────────────────────


@router.get(
    "/by-event/{event_id}",
    response_model=AlertListResponse,
)
async def list_alerts_for_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    only_active: Annotated[bool, Query()] = True,
    severity: Annotated[str | None, Query()] = None,
) -> AlertListResponse:
    """List alerts for an event, filtered by the caller's role.

    Owners see every alert tenant-scoped (full owner_message). Managers see
    only their bar's owner_and_manager alerts (manager_message text).
    Anomaly alerts are physically filtered out for non-owners.
    """
    service = AlertsService(db)
    return await service.list_for_event(
        tenant_id=current_user.tenant_id,
        event_id=event_id,
        user_role=current_user.role.value,
        user_bar_id=current_user.bar_id,
        only_active=only_active,
        severity=severity,
    )


# ─── GET /alerts/by-event/{event_id}/count ────────────────────────────────────


@router.get(
    "/by-event/{event_id}/count",
)
async def count_active_for_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> dict[str, int]:
    """Compact counts by severity for the top-bar badge and AlertsPage
    filter summary. Not role-filtered — count is aggregate; the detail
    list on the page IS role-filtered.
    """
    service = AlertsService(db)
    return await service.count_active(tenant_id, event_id)


# ─── GET /alerts/by-event/{event_id}/count-by-bar ─────────────────────────────


@router.get(
    "/by-event/{event_id}/count-by-bar",
)
async def count_active_by_bar(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, dict[str, int]]:
    """Per-bar active alert counts for Dashboard BarCard red-dot decision.

    Owner-only: managers never see alerts for other bars. Returning this
    to a manager would leak operational signal about bars they don't run.
    """
    if current_user.role.value != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "forbidden",
                "message": "Only Owners can view the bar-level alert map.",
            },
        )

    service = AlertsService(db)
    raw = await service.count_active_by_bar(current_user.tenant_id, event_id)
    # UUID keys → strings for JSON serialization
    return {str(bar_id): counts for bar_id, counts in raw.items()}


# ─── GET /alerts/{alert_id} ───────────────────────────────────────────────────


@router.get(
    "/{alert_id}",
    response_model=AlertResponse,
)
async def get_alert(
    alert_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AlertResponse:
    """Single alert detail, role-filtered.

    403 (not 404) on manager-visibility mismatch so we don't leak existence.
    """
    service = AlertsService(db)
    try:
        return await service.get_by_id(
            tenant_id=current_user.tenant_id,
            alert_id=alert_id,
            user_role=current_user.role.value,
            user_bar_id=current_user.bar_id,
        )
    except AlertNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "alert_not_found", "message": "No such alert."},
        )
    except AlertAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "forbidden",
                "message": "You do not have access to this alert.",
            },
        )


# ─── PATCH /alerts/{alert_id}/acknowledge ─────────────────────────────────────


@router.patch(
    "/{alert_id}/acknowledge",
    response_model=AlertAcknowledgeResponse,
)
async def acknowledge_alert(
    alert_id: UUID,
    payload: AlertAcknowledge,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AlertAcknowledgeResponse:
    """Acknowledge an alert. Optimistic lock via version.

    Owner-only for now — Managers cannot acknowledge. Revisit when we
    decide whether manager-ack is useful (probably a future setting).

    409 on version conflict. Client must refetch the alert and retry.
    """
    if current_user.role.value != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "forbidden",
                "message": "Only Owners can acknowledge alerts.",
            },
        )

    service = AlertsService(db)
    try:
        result = await service.acknowledge(
            tenant_id=current_user.tenant_id,
            alert_id=alert_id,
            user_id=current_user.id,
            expected_version=payload.version,
        )
        await db.commit()
        return result
    except AlertNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "alert_not_found", "message": "No such alert."},
        )
    except StaleAlertVersionError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "version_conflict",
                "message": "Alert was modified; refetch and retry.",
                "current_version": e.current_version,
            },
        )
    except AlertAlreadyAcknowledgedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "already_acknowledged",
                "message": "This alert was already acknowledged.",
            },
        )
