"""Phase 2 Stage 1 — the application layer knows exactly two roles.

BARTENDER and WAREHOUSE are retired: the enum members remain (historical
rows still carry them; the Postgres enum is untouched at this stage) but
no login, token, or grant may use them.

Covers:
  - ACTIVE_ROLES is exactly {OWNER, MANAGER}
  - /auth/login rejects requested_role=bartender/warehouse with a clear 403
    BEFORE credential verification (role-global rejection, no account info)
  - /auth/login legacy path (no requested_role) refuses accounts whose
    primary role is retired
  - /auth/roles-for-email never offers a retired role, even where a
    historical user_roles grant row still exists
  - Owner login is unchanged
  - the scan-permission matrix and warehouse guards know only owner/manager
  - the retired communication_tree seeder refuses to run
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.modules.auth.models import ACTIVE_ROLES, UserRole
from app.modules.warehouse.router import require_owner_or_manager
from app.modules.warehouse.scan_service import _ROLE_SCAN_PERMISSIONS

from tests.conftest import OWNER_EMAIL, OWNER_PASSWORD


# ─── The role set itself ──────────────────────────────────────────────


def test_active_roles_is_exactly_owner_and_manager() -> None:
    assert ACTIVE_ROLES == frozenset({UserRole.OWNER, UserRole.MANAGER})


def test_retired_enum_members_still_exist_for_historical_rows() -> None:
    # The Postgres enum is untouched in Stage 1; SQLAlchemy must still be
    # able to map existing BARTENDER/WAREHOUSE rows.
    assert UserRole("bartender") is UserRole.BARTENDER
    assert UserRole("warehouse") is UserRole.WAREHOUSE


# ─── Login endpoint ───────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("retired", ["bartender", "warehouse"])
async def test_login_rejects_retired_requested_role_regardless_of_credentials(
    client: AsyncClient, retired: str
) -> None:
    """A retired requested_role 403s before credentials are even checked —
    the same clear rejection for real accounts, wrong passwords, and
    unknown emails alike."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={
            "username": "anyone@example.com",
            "password": "irrelevant",
            "requested_role": retired,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 403, resp.text
    assert "retired" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("retired", ["bartender", "warehouse"])
async def test_login_rejects_retired_role_even_with_valid_owner_credentials(
    client: AsyncClient, retired: str
) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        data={
            "username": OWNER_EMAIL,
            "password": OWNER_PASSWORD,
            "requested_role": retired,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 403, resp.text
    assert "retired" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_unknown_role_still_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        data={
            "username": OWNER_EMAIL,
            "password": OWNER_PASSWORD,
            "requested_role": "superadmin",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_owner_login_unchanged(client: AsyncClient) -> None:
    for extra in ({}, {"requested_role": "owner"}):
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": OWNER_EMAIL, "password": OWNER_PASSWORD, **extra},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]


# ─── roles-for-email filtering ────────────────────────────────────────


@pytest.mark.asyncio
async def test_roles_for_email_never_offers_retired_roles(client: AsyncClient) -> None:
    """Accounts whose only grant is retired get an empty list — the same
    response as an unknown email. Dev DB seeds bartender.*@nomagroup.it
    with a BARTENDER grant row that still exists at this stage."""
    resp = await client.post(
        "/api/v1/auth/roles-for-email",
        json={"email": "bartender.marco@nomagroup.it"},
    )
    assert resp.status_code == 200
    assert resp.json()["roles"] == []


@pytest.mark.asyncio
async def test_roles_for_email_owner_unchanged(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/roles-for-email",
        json={"email": OWNER_EMAIL},
    )
    assert resp.status_code == 200
    roles = resp.json()["roles"]
    assert "owner" in roles
    assert set(roles) <= {"owner", "manager"}


# ─── Warehouse guards + scan matrix ───────────────────────────────────


class _MockUser:
    def __init__(self, role: UserRole) -> None:
        self.role = role


def test_require_owner_or_manager_allows_owner_and_manager() -> None:
    for role in (UserRole.OWNER, UserRole.MANAGER):
        assert require_owner_or_manager(_MockUser(role)).role is role


@pytest.mark.parametrize("retired", [UserRole.BARTENDER, UserRole.WAREHOUSE])
def test_require_owner_or_manager_rejects_retired_roles(retired: UserRole) -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_owner_or_manager(_MockUser(retired))
    assert exc_info.value.status_code == 403


def test_scan_matrix_knows_only_two_roles() -> None:
    assert set(_ROLE_SCAN_PERMISSIONS) == {"owner", "manager"}


def test_manager_scan_set_absorbs_intake_and_consumed() -> None:
    """Manager takes over warehouse execution (INTAKE, with the invoice
    lifecycle) and the retired Bartender's bar-floor CONSUMED scan.
    ADJUSTMENT / INSPECT stay Owner-only audit actions."""
    assert _ROLE_SCAN_PERMISSIONS["manager"] == {"INTAKE", "DISPATCH", "RETURN", "CONSUMED"}
    assert _ROLE_SCAN_PERMISSIONS["owner"] == {
        "INTAKE", "DISPATCH", "RETURN", "ADJUSTMENT", "INSPECT", "CONSUMED",
    }


# ─── Retired seeder ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_communication_tree_seeder_refuses_to_run() -> None:
    from app.seeds.communication_tree import seed

    with pytest.raises(RuntimeError, match="retired"):
        await seed()
