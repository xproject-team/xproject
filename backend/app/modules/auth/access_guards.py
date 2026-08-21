"""Shared role-based access guards for tenant + bar scoping.

Used by list endpoints to enforce that non-Owner roles cannot query data
for bars they aren't assigned to. Owner bypasses; Manager is locked to
their assignedBarId.

Spec: docs/bar-dashboard-spec.md S9.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status

from app.modules.auth.models import User, UserRole


class BarAccessDeniedError(Exception):
    """Internal exception; routers translate to HTTP 403."""


def assert_bar_access(user: User, requested_bar_id: UUID | None) -> None:
    """Verify the user is allowed to query data scoped to requested_bar_id.

    Behavior (two-role model):
      - Owner: always allowed (returns silently).
      - Manager: allowed ONLY when requested_bar_id matches their assigned
        bar. None (no filter) is treated as "all bars" and denied for
        non-Owner roles — they must scope explicitly.

    Raises HTTPException 403 with structured detail when denied. Routers
    can let the exception propagate; FastAPI will return the right status.
    """
    if user.role == UserRole.OWNER:
        return  # owner sees everything

    # Non-Owner roles MUST scope their queries
    if requested_bar_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "bar_id_required",
                "message": "Your role requires you to scope queries to a specific bar.",
            },
        )

    # Manager: lock to their assigned bar
    user_bar_id = getattr(user, "bar_id", None) or getattr(user, "assigned_bar_id", None)
    if user_bar_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "no_bar_assigned",
                "message": "Your account isn't assigned to a bar. Contact your tenant admin.",
            },
        )

    if user_bar_id != requested_bar_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "bar_access_denied",
                "message": "You can only access data for your assigned bar.",
            },
        )


def resolve_bar_filter(user: User, requested_bar_id: UUID | None) -> UUID | None:
    """Convenience helper: returns the bar_id to filter by.

    For Manager, if they didn't pass bar_id explicitly, returns their
    assigned bar (so the frontend doesn't have to remember to pass it).
    For Owner, returns whatever they passed (None = all bars).

    After this returns, the caller still calls assert_bar_access to verify
    the resolved bar_id is allowed.
    """
    if user.role == UserRole.OWNER:
        return requested_bar_id  # owner: explicit pass-through

    # Non-Owner: auto-fill from assignedBarId if not explicitly provided
    if requested_bar_id is None:
        user_bar_id = getattr(user, "bar_id", None) or getattr(user, "assigned_bar_id", None)
        return user_bar_id

    return requested_bar_id
