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

# ─────────────────────────────────────────────────────────────────────
# Async engine cleanup — prevents connection pool pollution across tests
# ─────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_after_test():
    """Dispose the app's async engine after every test to avoid asyncpg
    'another operation is in progress' errors caused by lingering
    connections shared across the test session.
    """
    yield
    from app.core.database import engine
    await engine.dispose()


# ─────────────────────────────────────────────────────────────────────
# Test-isolation fixtures — SAVEPOINT rollback per test
# ─────────────────────────────────────────────────────────────────────
# Opt-in fixtures: tests that request `db_session` or `isolated_client`
# run inside a transaction that auto-rolls back at test end. NOTHING
# they do persists to xproject_dev. Tests that don't request these
# fixtures keep working exactly as before (uses real committed data).
#
# The pattern is the standard SQLAlchemy nested-transaction idiom:
# https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction
#
# Why it's needed: the app's get_db() yields sessions bound to fresh
# connections. Without override, any HTTP call commits to the real DB.
# These fixtures override get_db so the app's session shares OUR
# connection inside OUR outer transaction — which we roll back at end.

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import engine as _app_engine, get_db as _app_get_db


@pytest_asyncio.fixture
async def db_session():
    """A transactional AsyncSession that rolls back at test end.

    Uses the documented SQLAlchemy 2.0 async pattern: open a
    connection, begin an outer transaction, build a session bound
    to that connection, and wrap each session.commit() in a
    SAVEPOINT via the session-level after_transaction_end event.

    Reference: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
    section on "Joining a session into an external transaction".

    At test end the outer rollback undoes every insert/update done
    during the test. xproject_dev is never mutated.
    """
    async with _app_engine.connect() as connection:
        # Outer transaction — held open for the entire test.
        outer = await connection.begin()

        # Build a session bound to OUR connection.
        TestSession = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            class_=AsyncSession,
            join_transaction_mode="create_savepoint",
        )
        session = TestSession()
        # Exposed so a test that needs MULTIPLE independent sessions bound
        # to this same connection/SAVEPOINT chain (e.g. simulating "each
        # cron event gets its own session" in test_event_auto_transitions.py)
        # can build them via async_sessionmaker(bind=session._test_connection,
        # join_transaction_mode="create_savepoint") — get_bind() doesn't
        # work for this: it returns the sync-facing connection proxy, not
        # the AsyncConnection async_sessionmaker requires. Doesn't change
        # db_session's behavior for any other test.
        session._test_connection = connection

        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


@pytest_asyncio.fixture
async def isolated_client(db_session: AsyncSession):
    """An AsyncClient where the app uses db_session for every request.

    Routes that depend on get_db() will receive OUR transactional
    session, so any inserts they perform are part of our SAVEPOINT
    and get rolled back at test end.

    Usage:
        async def test_endpoint(isolated_client, owner_headers):
            r = await isolated_client.post("/api/v1/events", ...,
                                            headers=owner_headers)
            assert r.status_code == 201
            # Whatever the endpoint created lives only inside our
            # transaction and disappears when the test exits.
    """
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[_app_get_db] = _override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(_app_get_db, None)
