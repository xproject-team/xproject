"""Tests for GET /api/v1/events/slesh-shops.

Three response modes verified:
  - live    : Slesh fetch succeeds, response.source == "live"
  - cached  : Pre-warmed Redis cache, response.source == "cached", no network call
  - offline : SleshAdapter raises, response.source == "offline", empty shops

The SleshAdapter is patched on the router module so we never hit the
real Slesh API in tests. Redis is real but uses a test-namespaced key
that the fixture wipes before each run.
"""
from __future__ import annotations
import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.auth.router import get_current_user
from app.core.database import get_db
from app.core.redis_client import get_redis
from tests.fixtures.alerts.factories import make_tenant
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio


class _FakeShop:
    """Mimics what SleshAdapter.list_shops returns (one element)."""
    def __init__(self, id_: str, name: str, is_enabled: bool = True):
        self.id = id_
        self.name = name
        self.is_enabled = is_enabled


async def _reset_redis_singleton() -> None:
    """Force the next get_redis() call to create a fresh client bound to
    THIS event loop. Without this, pytest-asyncio creates a new loop per
    test but the cached Redis client is still tied to the closed loop
    from the previous test, raising "Event loop is closed" on reuse."""
    import app.core.redis_client as rc
    if rc._redis is not None:
        try:
            await rc._redis.aclose()
        except Exception:  # noqa: BLE001
            pass
        rc._redis = None


async def _client_with_test_tenant():
    await _reset_redis_singleton()
    session = TestSessionLocal()
    tenant = await make_tenant(session)
    test_user = User(
        id=tenant.id,
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


async def _clear_cache_for(brand_id: str) -> None:
    # Reset the singleton first so we don\'t inherit a closed-loop client
    # from the previous test. Belt-and-suspenders with the reset inside
    # _client_with_test_tenant.
    await _reset_redis_singleton()
    redis = await get_redis()
    await redis.delete(f"slesh:shops:{brand_id}")


async def test_slesh_shops_live_success_returns_shops():
    """When Slesh returns shops, response.source is "live" and the
    payload is shaped correctly. Subsequent call within TTL is cached."""
    client, session, _ = await _client_with_test_tenant()
    try:
        # Use a unique brand id so cache reads from prior tests don’t bleed in
        from app.core.config import settings
        original_brand = settings.slesh_brand_id
        settings.slesh_brand_id = "test_brand_live_001"
        await _clear_cache_for(settings.slesh_brand_id)

        fake_shops = [
            _FakeShop("66501111", "Bar Main",  True),
            _FakeShop("66502222", "Bar n.3",   True),
            _FakeShop("66503333", "Malandrino", False),
        ]
        with patch(
            "app.modules.events.router.SleshAdapter"
        ) as MockAdapter:
            # SleshAdapter is used via `async with`. The construction
            # returns the MockAdapter instance; `__aenter__` must return
            # the adapter we want `list_shops` called on.
            inst = MockAdapter.return_value
            inst.__aenter__ = AsyncMock(return_value=inst)
            inst.__aexit__  = AsyncMock(return_value=None)
            inst.list_shops = AsyncMock(return_value=fake_shops)
            r = await client.get("/api/v1/events/slesh-shops")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "live"
        assert len(body["shops"]) == 3
        names = sorted(s["name"] for s in body["shops"])
        assert names == ["Bar Main", "Bar n.3", "Malandrino"]
        # is_active mirrors is_enabled
        malandrino = next(s for s in body["shops"] if s["name"] == "Malandrino")
        assert malandrino["is_active"] is False
        # Cleanup
        settings.slesh_brand_id = original_brand
        await _clear_cache_for("test_brand_live_001")
    finally:
        await client.aclose()
        await session.close()
        app.dependency_overrides.clear()


async def test_slesh_shops_cached_returns_without_calling_adapter():
    """If Redis has a fresh cache entry, the endpoint returns it without
    invoking the SleshAdapter at all."""
    from app.core.config import settings
    original_brand = settings.slesh_brand_id
    settings.slesh_brand_id = "test_brand_cached_001"
    await _clear_cache_for(settings.slesh_brand_id)

    # Pre-warm the cache
    redis = await get_redis()
    cached_payload = [
        {"id": "9999", "name": "Cached Bar", "is_active": True},
    ]
    await redis.setex(
        f"slesh:shops:{settings.slesh_brand_id}",
        60,
        json.dumps(cached_payload),
    )

    client, session, _ = await _client_with_test_tenant()
    try:
        with patch(
            "app.modules.events.router.SleshAdapter"
        ) as MockAdapter:
            inst = MockAdapter.return_value
            inst.list_shops = AsyncMock(return_value=[])
            r = await client.get("/api/v1/events/slesh-shops")
            # Adapter should NEVER have been instantiated
            MockAdapter.assert_not_called()
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "cached"
        assert body["shops"] == cached_payload
        assert body["cache_ttl_s"] > 0
        # Cleanup
        settings.slesh_brand_id = original_brand
        await _clear_cache_for("test_brand_cached_001")
    finally:
        await client.aclose()
        await session.close()
        app.dependency_overrides.clear()


async def test_slesh_shops_offline_when_adapter_raises():
    """When the SleshAdapter raises (network/timeout/auth), the endpoint
    must still return 200 with source="offline" and shops=[]. This is the
    "no crash on Sundance day" guarantee — the wizard’s manual
    fallback kicks in client-side."""
    from app.core.config import settings
    original_brand = settings.slesh_brand_id
    settings.slesh_brand_id = "test_brand_offline_001"
    await _clear_cache_for(settings.slesh_brand_id)

    client, session, _ = await _client_with_test_tenant()
    try:
        with patch(
            "app.modules.events.router.SleshAdapter"
        ) as MockAdapter:
            # Async-context-manager protocol; list_shops raises inside
            # the `async with` block. The endpoint\'s try/except must
            # catch and return offline.
            inst = MockAdapter.return_value
            inst.__aenter__ = AsyncMock(return_value=inst)
            inst.__aexit__  = AsyncMock(return_value=None)
            inst.list_shops = AsyncMock(side_effect=ConnectionError("network down"))
            r = await client.get("/api/v1/events/slesh-shops")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "offline"
        assert body["shops"] == []
        assert body["cache_ttl_s"] == 0
        # Cleanup
        settings.slesh_brand_id = original_brand
        await _clear_cache_for("test_brand_offline_001")
    finally:
        await client.aclose()
        await session.close()
        app.dependency_overrides.clear()


async def test_slesh_shops_offline_when_brand_id_missing():
    """When SLESH_BRAND_ID env var is unset, do NOT 500 — return
    offline so the wizard offers manual entry."""
    from app.core.config import settings
    original_brand = settings.slesh_brand_id
    settings.slesh_brand_id = ""

    client, session, _ = await _client_with_test_tenant()
    try:
        r = await client.get("/api/v1/events/slesh-shops")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "offline"
        assert body["shops"] == []
        # Cleanup
        settings.slesh_brand_id = original_brand
    finally:
        await client.aclose()
        await session.close()
        app.dependency_overrides.clear()
