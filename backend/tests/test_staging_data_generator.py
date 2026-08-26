"""Staging data generator — build it, prove accounts can actually log in.

Two findings drive the shape of these tests:

  1. The role lives in TWO places and login-via-the-UI reads user_roles
     (the multi-role source of truth — auth/repository.py says so
     explicitly), NOT users.role. A user with only users.role set cannot
     log in through the frontend. So these tests prove LOGIN SUCCEEDS
     through the real /auth endpoints with requested_role — not merely
     that rows exist.
  2. The generator must be impossible to run against production by
     accident: an explicit environment marker gate, tested here.

Written FIRST, before the generator existed, per the failing-test rule.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from tests.fixtures.alerts.session import TestSessionLocal

pytestmark = pytest.mark.asyncio

GENERATOR_SLUGS = ("staging-alpha", "staging-beta")


def _arm_staging_markers(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setattr(settings, "pos_adapter", "fake")
    monkeypatch.setattr(settings, "slesh_api_token", "")


async def _tenant_count() -> int:
    from app.modules.auth.models import Tenant

    async with TestSessionLocal() as s:
        return (await s.execute(
            select(func.count()).select_from(Tenant).where(Tenant.slug.in_(GENERATOR_SLUGS))
        )).scalar_one()


async def _login(client: AsyncClient, email: str, password: str, role: str) -> dict:
    """The frontend's exact two-step flow: roles-for-email, then login
    WITH requested_role — the path that fails when user_roles is empty."""
    r = await client.post("/api/v1/auth/roles-for-email", json={"email": email})
    assert r.status_code == 200, r.text
    assert role in r.json()["roles"], (
        f"{email}: role {role!r} missing from roles-for-email — the "
        "user_roles table (the authoritative one) was not populated"
    )
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password, "requested_role": role},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, f"{email} as {role}: {r.status_code} {r.text}"
    body = r.json()
    assert body["access_token"]
    return body


async def test_guard_refuses_without_the_staging_marker(monkeypatch):
    """No ENVIRONMENT=staging → refuse before touching anything; a
    production-shaped environment (ENVIRONMENT=production, real adapter,
    token present) must also refuse."""
    from app.scripts.build_staging_data import StagingGuardError, build

    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with pytest.raises(StagingGuardError):
        await build(fast=True)

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "pos_adapter", "slesh")
    monkeypatch.setattr(settings, "slesh_api_token", "real-token")
    with pytest.raises(StagingGuardError):
        await build(fast=True)

    # Marker alone is not enough: staging must also be on the fake
    # adapter with no Slesh credential in the environment.
    monkeypatch.setenv("ENVIRONMENT", "staging")
    with pytest.raises(StagingGuardError):
        await build(fast=True)

    assert await _tenant_count() == 0, "a refused run must write nothing"


async def test_build_structure_and_real_login(monkeypatch):
    from app.main import app
    from app.modules.auth.models import Tenant, User, UserRoleAssignment
    from app.modules.bars.models import Bar
    from app.modules.events.models import Event, EventStatus
    from app.modules.pos.adapters.fake import FAKE_PRODUCTS_RAW, FAKE_SHOPS_RAW
    from app.modules.products.models import Product
    from app.scripts.build_staging_data import ACCOUNTS, build, wipe

    _arm_staging_markers(monkeypatch)
    try:
        summary = await build(fast=True)
        assert summary["tenants"] == 2

        async with TestSessionLocal() as s:
            tenants = {
                t.slug: t for t in (await s.execute(
                    select(Tenant).where(Tenant.slug.in_(GENERATOR_SLUGS))
                )).scalars()
            }
            assert set(tenants) == set(GENERATOR_SLUGS)
            alpha, beta = tenants["staging-alpha"], tenants["staging-beta"]

            # Events: alpha covers every lifecycle state; beta has NO
            # completed events (the insufficient-history tenant).
            alpha_states = {
                str(e.status.value) for e in (await s.execute(
                    select(Event).where(Event.tenant_id == alpha.id)
                )).scalars()
            }
            assert {"draft", "active", "live", "completed"} <= alpha_states
            completed_alpha = (await s.execute(
                select(func.count()).select_from(Event).where(
                    Event.tenant_id == alpha.id, Event.status == EventStatus.COMPLETED,
                )
            )).scalar_one()
            assert completed_alpha >= 3
            completed_beta = (await s.execute(
                select(func.count()).select_from(Event).where(
                    Event.tenant_id == beta.id, Event.status == EventStatus.COMPLETED,
                )
            )).scalar_one()
            assert completed_beta == 0

            # Catalog: every product carries an external_pos_id from the
            # fake adapter's catalog, so ingested orders deplete stock.
            fake_ids = {p["_id"] for p in FAKE_PRODUCTS_RAW}
            mapped_ids = set((await s.execute(
                select(Product.external_pos_id).where(
                    Product.tenant_id == alpha.id,
                    Product.external_pos_id.is_not(None),
                )
            )).scalars())
            assert mapped_ids == fake_ids

            # Bars: both types; mappings come from the fake shop list;
            # EXACTLY ONE bar is deliberately unmapped (parking rehearsal).
            bars = (await s.execute(
                select(Bar).where(Bar.tenant_id == alpha.id)
            )).scalars().all()
            assert {b.bar_type for b in bars} >= {"drinks", "food"}
            shop_ids = {sh["_id"] for sh in FAKE_SHOPS_RAW}
            mapped = [b for b in bars if b.slesh_negozio_id is not None]
            unmapped = [b for b in bars if b.slesh_negozio_id is None]
            assert all(b.slesh_negozio_id in shop_ids for b in mapped)
            assert len(unmapped) == 1, (
                "exactly one deliberately-unmapped bar must exist "
                f"(got {[(b.name, b.slesh_negozio_id) for b in unmapped]})"
            )

            # Both role columns written — users.role AND user_roles.
            for email, _pw, role, tenant_slug in ACCOUNTS:
                user = (await s.execute(
                    select(User).where(User.email == email)
                )).scalar_one()
                assert user.tenant_id == tenants[tenant_slug].id
                assignments = set((await s.execute(
                    select(UserRoleAssignment.role).where(
                        UserRoleAssignment.user_id == user.id,
                    )
                )).scalars())
                assert assignments, f"{email}: empty user_roles cannot log in"

        # Both roles LOG IN through the real endpoints, frontend-style.
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            roles_seen = set()
            for email, password, role, _slug in ACCOUNTS:
                await _login(client, email, password, role)
                roles_seen.add(role)
            assert {"owner", "manager"} <= roles_seen

        # Idempotent: a second run rebuilds from scratch, same shape.
        summary2 = await build(fast=True)
        assert summary2["tenants"] == 2
        assert await _tenant_count() == 2
    finally:
        await wipe()
        assert await _tenant_count() == 0
