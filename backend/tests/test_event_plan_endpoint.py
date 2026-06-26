"""Tests for POST /api/v1/events/import-plan.

These are integration tests against the FastAPI app — they exercise
the route registration, multipart upload, and tenant auth, on top of
the parser tests in test_event_plan_excel.py.
"""
from __future__ import annotations
import io
from pathlib import Path

import openpyxl
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from tests.fixtures.alerts.factories import make_tenant
from tests.fixtures.alerts.session import TestSessionLocal
from app.modules.auth.router import get_current_user
from app.core.database import get_db
from app.modules.auth.models import User, UserRole

pytestmark = pytest.mark.asyncio


FIXTURE = Path(__file__).parent / "fixtures" / "excel" / "sundance_2026_plan.xlsx"


async def _client_with_test_tenant():
    """Build an AsyncClient pointing at the FastAPI app, with auth
    + DB dependency overrides so we don't need a real JWT or live DB.
    Returns (client, tenant, session_factory)."""
    session = TestSessionLocal()
    tenant = await make_tenant(session)

    # Create a fake current_user that the auth dep will return
    test_user = User(
        id=tenant.id,                          # any UUID will do
        tenant_id=tenant.id,
        email="test@example.it",
        hashed_password="x",
        full_name="Test User",
        role=UserRole.OWNER,
        is_active=True,
    )

    async def _override_db():
        yield session

    async def _override_user():
        return test_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    return client, session, tenant


async def test_import_plan_happy_path_returns_parsed_json():
    """Upload the real fixture, get back 200 + the expected structure."""
    client, session, tenant = await _client_with_test_tenant()
    try:
        with FIXTURE.open("rb") as f:
            r = await client.post(
                "/api/v1/events/import-plan",
                files={"file": ("plan.xlsx", f,
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        # Spot-check known fields from the real fixture
        assert body["event_name"] == "Sundance Sunday"
        assert body["event_start_time"] == "12:30"
        assert body["event_end_time"] == "22:30"
        assert body["capacity"] == 1600
        # drink + food bars present
        drink_names = sorted(b["name"] for b in body["drink_bars"])
        assert "MAIN BAR" in drink_names
        food_names = sorted(b["name"] for b in body["food_bars"])
        assert "MALANDRINO" in food_names
        # event_dates is the 4-date multi-event list
        assert body["event_dates"] == ["14/06", "05/07", "19/07", "02/08"]
    finally:
        await client.aclose()
        await session.close()
        app.dependency_overrides.clear()


async def test_import_plan_empty_body_returns_400():
    """An upload with empty bytes should be rejected up-front, not
    passed to the parser."""
    client, session, _ = await _client_with_test_tenant()
    try:
        r = await client.post(
            "/api/v1/events/import-plan",
            files={"file": ("empty.xlsx", b"", "application/octet-stream")},
        )
        assert r.status_code == 400, r.text
        assert "empty" in r.json()["detail"].lower()
    finally:
        await client.aclose()
        await session.close()
        app.dependency_overrides.clear()


async def test_import_plan_oversized_file_returns_413():
    """Any upload >2 MB must be rejected with 413, regardless of content.

    Use random (incompressible) bytes — earlier attempt built a real
    xlsx of 500x5KB rows, but xlsx zip-compression squashed it to ~12 KB
    and the size guard never fired. The endpoint guards on raw upload
    bytes, not on parsed content, so the content type doesn't matter
    for this check.
    """
    import os as _os
    client, session, _ = await _client_with_test_tenant()
    try:
        oversized = _os.urandom(3 * 1024 * 1024)   # 3 MB of random bytes
        assert len(oversized) > 2 * 1024 * 1024

        r = await client.post(
            "/api/v1/events/import-plan",
            files={"file": ("big.xlsx", oversized,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert r.status_code == 413, r.text
        assert "too large" in r.json()["detail"].lower()
    finally:
        await client.aclose()
        await session.close()
        app.dependency_overrides.clear()


async def test_import_plan_garbage_bytes_returns_200_with_warnings():
    """A junk file (not real xlsx) should NOT 500; the parser catches it
    and returns a ParsedEventPlan with an open-workbook warning."""
    client, session, _ = await _client_with_test_tenant()
    try:
        r = await client.post(
            "/api/v1/events/import-plan",
            files={"file": ("junk.xlsx", b"this is not an xlsx file",
                            "application/octet-stream")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Empty lists, no event name — but warnings populated
        assert body["event_name"] is None
        assert body["drink_bars"] == []
        assert len(body["warnings"]) >= 1
        assert any("could not open" in w["message"] for w in body["warnings"])
    finally:
        await client.aclose()
        await session.close()
        app.dependency_overrides.clear()
