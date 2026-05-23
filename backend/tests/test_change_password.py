"""HTTP integration tests for POST /auth/change-password (F5).

Uses the live dev DB via the in-process ASGITransport.  Because we mutate
the Owner's password during the success test, we restore it at the end of
each successful run to keep other tests stable.

Coverage:
  - success (204, new password verifies, old does not)
  - wrong old password (401)
  - new password too short (400)
  - new password same as old (400)
  - unauthenticated request (401)
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

# Standard owner creds from conftest.py
OWNER_EMAIL = "omar@nomagroup.it"
OWNER_PASSWORD = "xproject2026"


async def _login(client: AsyncClient, email: str, password: str) -> int:
    """POST /auth/login with form-encoded body.  Returns HTTP status."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return resp.status_code


@pytest.mark.asyncio
async def test_change_password_success_and_restore(
    client: AsyncClient, owner_headers: dict[str, str]
):
    """Owner changes password, new one logs in, old one fails, then restore."""
    new_pw = "tempSundance2026!"

    # Change
    res = await client.post(
        "/api/v1/auth/change-password",
        headers=owner_headers,
        json={"old_password": OWNER_PASSWORD, "new_password": new_pw},
    )
    assert res.status_code == 204, res.text

    # New password works
    assert await _login(client, OWNER_EMAIL, new_pw) == 200

    # Old password no longer works
    assert await _login(client, OWNER_EMAIL, OWNER_PASSWORD) == 401

    # Restore: re-login with new, get fresh token, change back to original
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": OWNER_EMAIL, "password": new_pw},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login.status_code == 200
    new_token = login.json()["access_token"]

    restore = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {new_token}"},
        json={"old_password": new_pw, "new_password": OWNER_PASSWORD},
    )
    assert restore.status_code == 204, restore.text

    # Sanity: original creds work again
    assert await _login(client, OWNER_EMAIL, OWNER_PASSWORD) == 200


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_old(
    client: AsyncClient, owner_headers: dict[str, str]
):
    res = await client.post(
        "/api/v1/auth/change-password",
        headers=owner_headers,
        json={"old_password": "definitely-wrong", "new_password": "anything12345"},
    )
    assert res.status_code == 401
    assert "Old password is incorrect" in res.json()["detail"]


@pytest.mark.asyncio
async def test_change_password_rejects_short_new(
    client: AsyncClient, owner_headers: dict[str, str]
):
    res = await client.post(
        "/api/v1/auth/change-password",
        headers=owner_headers,
        json={"old_password": OWNER_PASSWORD, "new_password": "short"},
    )
    assert res.status_code == 400
    assert "at least 8 characters" in res.json()["detail"]


@pytest.mark.asyncio
async def test_change_password_rejects_same_as_old(
    client: AsyncClient, owner_headers: dict[str, str]
):
    res = await client.post(
        "/api/v1/auth/change-password",
        headers=owner_headers,
        json={"old_password": OWNER_PASSWORD, "new_password": OWNER_PASSWORD},
    )
    assert res.status_code == 400
    assert "differ from the old one" in res.json()["detail"]


@pytest.mark.asyncio
async def test_change_password_requires_auth(client: AsyncClient):
    res = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": OWNER_PASSWORD, "new_password": "anything12345"},
    )
    assert res.status_code == 401



# ── End-to-end wire test on a throwaway user ─────────────────────────────────


@pytest.mark.asyncio
async def test_change_password_throwaway_user(client: AsyncClient):
    """Full HTTP flow on a freshly-created user.  No seed account touched.

    Covers in one flow:
      - 400 on length, 400 on same-as-old, 401 on wrong-old (client-side
        validators are bypassed because we're hitting HTTP directly)
      - 204 on success
      - new password authenticates, old does not
      - cleanup deletes the user regardless of outcome
    """
    import uuid
    from sqlalchemy import select, delete

    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.modules.auth.models import Tenant, User, UserRole

    initial_password = "initial-pw-9999"
    new_password = "rotated-pw-12345"
    short_password = "short"
    email = f"f5-throwaway-{uuid.uuid4().hex[:8]}@example.test"

    # ── 1. Create throwaway user under an existing tenant ─────────────
    async with AsyncSessionLocal() as session:
        tenant_row = (await session.execute(select(Tenant).limit(1))).scalar_one()
        user = User(
            tenant_id=tenant_row.id,
            email=email,
            hashed_password=hash_password(initial_password),
            full_name="F5 Throwaway User",
            role=UserRole.OWNER,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        user_id = user.id

    try:
        # ── 2. Log in as throwaway user ───────────────────────────────
        login = await client.post(
            "/api/v1/auth/login",
            data={"username": email, "password": initial_password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # ── 3. 400 — new password too short ───────────────────────────
        resp = await client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"old_password": initial_password, "new_password": short_password},
        )
        assert resp.status_code == 400, resp.text

        # ── 4. 400 — new same as old ──────────────────────────────────
        resp = await client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"old_password": initial_password, "new_password": initial_password},
        )
        assert resp.status_code == 400, resp.text

        # ── 5. 401 — wrong old password ───────────────────────────────
        resp = await client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"old_password": "wrong-old-credential", "new_password": new_password},
        )
        assert resp.status_code == 401, resp.text

        # ── 6. 204 — success ──────────────────────────────────────────
        resp = await client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"old_password": initial_password, "new_password": new_password},
        )
        assert resp.status_code == 204, resp.text

        # ── 7. New password authenticates; old does not ───────────────
        relogin_new = await client.post(
            "/api/v1/auth/login",
            data={"username": email, "password": new_password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert relogin_new.status_code == 200, relogin_new.text

        relogin_old = await client.post(
            "/api/v1/auth/login",
            data={"username": email, "password": initial_password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert relogin_old.status_code == 401, relogin_old.text

    finally:
        # ── 8. Cleanup regardless of outcome ──────────────────────────
        async with AsyncSessionLocal() as session:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
