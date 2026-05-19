"""Authorization helpers for the auth module.

This module provides the canonical 'what role is this user acting as?'
helper used by all routes for authorization decisions.

Phase 1D migration target: all routes that previously read
`current_user.role` directly are migrated to call `get_active_role`
instead.  The indirection lets us evolve the underlying source of
truth (DB column today, possibly user_roles join table tomorrow)
without touching call sites.
"""
from __future__ import annotations

from fastapi import HTTPException, status

from app.modules.auth.models import User, UserRole


def get_active_role(current_user: User) -> UserRole:
    """Return the role the user is currently acting as.

    Today (Phase 1D-min), reads current_user.role which is set by
    the get_current_user dependency from the JWT active_role claim
    (the dependency honors the claim and overrides the in-memory
    user.role accordingly).

    Future (Phase 1D-full), this is the extension point for
    stricter validation: cross-check the claim against the
    user_roles join table at request time, reject if the user
    no longer holds that role.

    Args:
        current_user: User model returned by get_current_user dependency.

    Returns:
        UserRole the user is currently acting as.

    Raises:
        HTTPException 401: if current_user has no role set.  Should
                            not occur in practice since get_current_user
                            raises 401 earlier when token is missing.
    """
    if not current_user.role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No active role set",
        )
    return current_user.role
