"""HTTP-layer regression tripwires for Phase 1B multi-role auth.

⚠️  This file uses the same trimmed-test discipline as test_reports_flow.py:
ONE HTTP call per test, no chained calls. The full Phase 1B end-to-end was
manually verified via curl during the 1B session (see commit message).
The asyncpg "another operation in progress" issue (Appendix A in
sundance-readiness-roadmap.md) blocks DB-write tests from running in the
same asyncio session as the FastAPI client. These tripwires catch the
highest-value regressions; the rest is covered by manual + browser tests
in Phase 1C.

Tracked deferred coverage:
  - login backward compat (no requested_role)
  - login with valid requested_role (JWT carries active_role)
  - login with unknown role string → 422
  - login with unauthorized role → 403
  - login with wrong password → 401 (pre-empts role check)

These five are manually validated via curl during the 1B work session.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


OWNER_EMAIL = "omar@nomagroup.it"


# ─── /auth/roles-for-email — happy path ────────────────────────────────────
# Catches: endpoint registered, 1A backfill consistent, repository helper works.

@pytest.mark.asyncio
async def test_roles_for_email_returns_assigned_roles(client: AsyncClient):
    """Owner email returns ['owner']. Transitively verifies 1A backfill + ORM."""
    resp = await client.post(
        "/api/v1/auth/roles-for-email",
        json={"email": OWNER_EMAIL},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == OWNER_EMAIL
    assert body["roles"] == ["owner"]


# ─── /auth/roles-for-email — input validation ──────────────────────────────
# Catches: Pydantic EmailStr is wired (frontend cannot bypass with garbage).

@pytest.mark.asyncio
async def test_roles_for_email_invalid_email_returns_422(client: AsyncClient):
    """Pydantic EmailStr rejects malformed strings. No DB call needed."""
    resp = await client.post(
        "/api/v1/auth/roles-for-email",
        json={"email": "not-an-email"},
    )
    assert resp.status_code == 422
