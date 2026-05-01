"""pytest fixtures — async test client, test database session, and auth helpers.

Tests run in-process against the real FastAPI app via ASGITransport (no
external server needed). Database is the live dev DB — tests must clean
up any rows they create. See test_reports_flow.py for the cleanup pattern.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


# Owner credentials for the default test tenant. These are the standard
# dev creds seeded by the initial data scripts; tests assume they exist.
OWNER_EMAIL = "omar@nomagroup.it"
OWNER_PASSWORD = "xproject2026"


@pytest_asyncio.fixture
async def client():
    """Async HTTP test client bound to the FastAPI app in-process."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def owner_token(client: AsyncClient) -> str:
    """Log in as the default Owner and return the Bearer token string.

    The /auth/login endpoint uses OAuth2 password flow (form-encoded body),
    not JSON. Tests that need authenticated calls should depend on this
    fixture and pass the returned token in an Authorization header:

        headers = {"Authorization": f"Bearer {owner_token}"}
    """
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": OWNER_EMAIL, "password": OWNER_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, f"Owner login failed: {resp.text}"
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def owner_headers(owner_token: str) -> dict[str, str]:
    """Convenience fixture: Authorization header dict for Owner calls."""
    return {"Authorization": f"Bearer {owner_token}"}


# ─────────────────────────────────────────────────────────────────────
# Slesh API fixtures — Layer 2 of the sandbox-defense strategy
# ─────────────────────────────────────────────────────────────────────
import json
from pathlib import Path as _Path


_SLESH_FIXTURE_DIR = _Path(__file__).parent / "fixtures" / "slesh"


@pytest.fixture
def slesh_fixture():
    """Load a recorded Slesh API response from disk.

    Usage:
        def test_brand_parses(slesh_fixture):
            raw = slesh_fixture("brand_my")
            brand = Brand.model_validate(raw)
            assert brand.id == "6650c69e25fcbf370f6fcc16"

    The fixture loader returns a callable so tests can request multiple
    fixtures in one test without nested dependencies. Filenames are passed
    WITHOUT the `.json` suffix.

    See backend/tests/fixtures/slesh/README.md for the full fixture catalog
    and re-recording procedure.
    """
    def _load(name: str) -> dict | list:
        path = _SLESH_FIXTURE_DIR / f"{name}.json"
        if not path.exists():
            available = sorted(p.stem for p in _SLESH_FIXTURE_DIR.glob("*.json"))
            raise FileNotFoundError(
                f"Slesh fixture {name!r} not found. "
                f"Available: {available}. "
                f"Looked in: {_SLESH_FIXTURE_DIR}"
            )
        return json.loads(path.read_text())
    return _load
