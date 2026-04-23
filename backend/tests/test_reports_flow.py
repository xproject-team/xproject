"""Integration tests for the Reports module (Phase 1.8 — minimal harness).

This is the project's first test file. It establishes the testing baseline
and covers the two highest-value regression risks:
  - Unauthenticated calls must return 401 (auth dependency is wired)
  - PortfolioKpis JSON shape cannot drift silently

Tests that write/read from the DB inside a test are DEFERRED. Running them
inside the same asyncio session as the FastAPI app client currently triggers
asyncpg's "another operation is in progress" error — a known interaction
between httpx.AsyncClient, async_sessionmaker, and pytest-asyncio 0.23 that
requires dedicated test-infra work to resolve (likely a get_db dependency
override via app.dependency_overrides, plus per-test engine disposal).

The full end-to-end pipeline WAS validated manually over real HTTP at the
end of Phase 1.7 — see commit 9bcef10's message. That's the substantive
proof; these automated tests exist as regression tripwires on top.

Tracked for future work:
  - Tenant isolation test (GET /reports/{id} with another tenant's ID → 404)
  - Generate/regenerate happy path with DB-backed fixtures
  - Role gate test (manager → 403)
  - Full idempotency + superseded_by verification

Spec: docs/report-module-spec.md §7 + §10.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


# ─── 1. Auth gate ───────────────────────────────────────────────────────────
# Catches the #1 security regression risk: someone removes the require_owner
# dependency by accident. Every protected endpoint must return 401 without
# a Bearer token, regardless of HTTP method or payload.

@pytest.mark.asyncio
async def test_unauthenticated_calls_return_401(client: AsyncClient):
    """All report endpoints require authentication. Missing Bearer → 401."""
    endpoints = [
        ("GET",  "/api/v1/reports"),
        ("GET",  "/api/v1/reports/portfolio/kpis"),
        ("POST", "/api/v1/reports/generate"),
        ("GET",  f"/api/v1/reports/{uuid.uuid4()}"),
        ("GET",  f"/api/v1/reports/{uuid.uuid4()}/pdf"),
    ]
    for method, path in endpoints:
        resp = await client.request(method, path)
        assert resp.status_code == 401, (
            f"{method} {path} expected 401, got {resp.status_code}"
        )


# ─── 2. PortfolioKpis JSON shape ────────────────────────────────────────────
# Catches schema drift between Pydantic schemas.py and frontend TS
# interfaces. If anyone renames a field or changes its type, this test
# fails immediately and the frontend team sees the contract breakage.

@pytest.mark.asyncio
async def test_portfolio_kpis_returns_valid_shape(
    client: AsyncClient,
    owner_headers: dict,
):
    """GET /reports/portfolio/kpis returns PortfolioKpis JSON with all expected fields."""
    resp = await client.get("/api/v1/reports/portfolio/kpis", headers=owner_headers)
    assert resp.status_code == 200
    body = resp.json()

    expected_keys = {
        "total_events_completed",
        "lifetime_revenue",
        "avg_event_revenue",
        "best_event_name",
        "best_event_revenue",
        "events_delta_vs_last_quarter",
        "revenue_delta_pct_yoy",
        "avg_revenue_delta_vs_last_quarter",
    }
    assert set(body.keys()) == expected_keys, (
        f"PortfolioKpis shape drift. Expected {expected_keys}, got {set(body.keys())}"
    )
    assert isinstance(body["total_events_completed"], int)
    assert body["total_events_completed"] >= 0
