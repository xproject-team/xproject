"""Unit tests for app.modules.auth.permissions.get_active_role.

These tests use mock User objects (not DB fixtures) since the helper
is pure — it reads an attribute that was set elsewhere (by the
get_current_user dependency).  Integration of helper with the
dependency is covered by the router-level migration tests.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.modules.auth.models import UserRole
from app.modules.auth.permissions import get_active_role


class _MockUser:
    """Minimal stand-in for the User SQLAlchemy model."""

    def __init__(self, role: UserRole | None) -> None:
        self.role = role


def test_returns_role_when_set() -> None:
    user = _MockUser(role=UserRole.OWNER)
    assert get_active_role(user) is UserRole.OWNER


def test_returns_role_for_each_role_value() -> None:
    for role in (UserRole.OWNER, UserRole.MANAGER, UserRole.BARTENDER, UserRole.WAREHOUSE):
        user = _MockUser(role=role)
        assert get_active_role(user) is role


def test_raises_401_when_role_is_none() -> None:
    user = _MockUser(role=None)
    with pytest.raises(HTTPException) as exc_info:
        get_active_role(user)
    assert exc_info.value.status_code == 401
    assert "No active role" in exc_info.value.detail
