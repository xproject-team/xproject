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

            # Bars: both types. Shop mappings must be held by the LIVE
            # event ONLY — the ingester resolves bars by (tenant, shop
            # id) with no event filter, so a shop id mapped on several
            # events at once resolves arbitrarily (the staging Day-4
            # BarNotInEventError storm). On the live event, exactly one
            # bar (Food Truck) is deliberately unmapped so parking is
            # rehearsed with a mapping an operator can actually resolve.
            bars = (await s.execute(
                select(Bar).where(Bar.tenant_id == alpha.id)
            )).scalars().all()
            assert {b.bar_type for b in bars} >= {"drinks", "food"}
            shop_ids = {sh["_id"] for sh in FAKE_SHOPS_RAW}
            live_event = next(
                e for e in (await s.execute(
                    select(Event).where(Event.tenant_id == alpha.id)
                )).scalars() if e.status == EventStatus.LIVE
            )
            mapped = [b for b in bars if b.slesh_negozio_id is not None]
            assert mapped, "the live event must carry shop mappings"
            assert all(b.event_id == live_event.id for b in mapped), (
                "shop ids may be mapped on the LIVE event only — a "
                "mapping on any other event makes bar resolution ambiguous"
            )
            assert all(b.slesh_negozio_id in shop_ids for b in mapped)
            live_unmapped = [
                b for b in bars
                if b.event_id == live_event.id and b.slesh_negozio_id is None
            ]
            assert len(live_unmapped) == 1 and live_unmapped[0].name == "Food Truck", (
                f"got {[(b.name, b.slesh_negozio_id) for b in live_unmapped]}"
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


async def test_build_history_reports_and_rehearsal_shapes(monkeypatch):
    """The layer every real failure this engagement lived in: ingested
    POS history through the real pipeline, reports with DIVERGED language
    versions (the only shape that surfaces the 22-Aug sibling-collision
    defect), a failed report row, unresolved parking, depletion inputs,
    and forecast artifacts for alpha but NOT beta."""
    from app.modules.auth.models import Tenant
    from app.modules.bar_stock.models import BarStock
    from app.modules.event_storage.models import (
        EventCategoryIngredient,
        EventStockBarAllocation,
        SupplierProduct,
    )
    from app.modules.events.models import Event, EventOrder, EventStatus
    from app.modules.pos.models import PendingShopMapping
    from app.modules.predictions.models import ModelArtifact
    from app.modules.recipes.models import Recipe, RecipeItem
    from app.modules.reports.models import Report
    from app.modules.stock_transactions.models import StockTransaction
    from app.scripts.build_staging_data import build, wipe

    _arm_staging_markers(monkeypatch)
    try:
        await build(fast=True)

        async with TestSessionLocal() as s:
            alpha = (await s.execute(
                select(Tenant).where(Tenant.slug == "staging-alpha")
            )).scalar_one()
            beta = (await s.execute(
                select(Tenant).where(Tenant.slug == "staging-beta")
            )).scalar_one()

            completed = (await s.execute(
                select(Event).where(
                    Event.tenant_id == alpha.id,
                    Event.status == EventStatus.COMPLETED,
                ).order_by(Event.scheduled_at)
            )).scalars().all()
            assert len(completed) >= 3

            # Real ingested history: event_orders + stock lines, with the
            # verified fiscal identity intact on every stored row, and
            # bar_stock_id stamped so burn-rate depletion can compute.
            eo = (await s.execute(
                select(EventOrder).where(EventOrder.tenant_id == alpha.id)
            )).scalars().all()
            assert len(eo) > 100
            for row in eo:
                assert row.subtotal_cents == row.fiscal_gross_cents + row.deposit_cents
            st = (await s.execute(
                select(StockTransaction).where(StockTransaction.tenant_id == alpha.id)
            )).scalars().all()
            assert st
            assert any(r.bar_stock_id is not None for r in st), (
                "stock lines must decrement bar_stock or the depletion "
                "evaluator has nothing to compute burn rates from"
            )

            # Unresolved parking exists (ghost-shop orders and/or the
            # deliberately-unmapped bar).
            parked = (await s.execute(
                select(PendingShopMapping).where(
                    PendingShopMapping.tenant_id == alpha.id,
                    PendingShopMapping.resolved_at.is_(None),
                )
            )).scalars().all()
            assert parked

            # Depletion inputs: allocations, recipes, storage layer.
            for model in (BarStock, Recipe, RecipeItem, SupplierProduct,
                          EventStockBarAllocation, EventCategoryIngredient):
                rows = (await s.execute(
                    select(func.count()).select_from(model).where(
                        model.tenant_id == alpha.id
                    )
                )).scalar_one()
                assert rows > 0, f"{model.__name__} not seeded"

            # Reports: both languages; one event carries the DIVERGED
            # shape (IT latest v1, EN latest v2, EN v1 superseded); at
            # least one failed row exists.
            reports = (await s.execute(
                select(Report).where(Report.tenant_id == alpha.id)
            )).scalars().all()
            assert {r.language for r in reports} == {"it", "en"}
            assert any(r.status == "failed" for r in reports)

            def _max_version(event_id, language):
                versions = [
                    r.version for r in reports
                    if r.event_id == event_id and r.language == language
                    and r.status == "ready"
                ]
                return max(versions) if versions else 0

            diverged = [
                e for e in completed
                if _max_version(e.id, "it") == 1 and _max_version(e.id, "en") == 2
            ]
            assert diverged, (
                "one event must carry IT v1 / EN v2 — the asymmetric shape "
                "that surfaces the sibling-collision defect fixed 22 Aug"
            )
            en_v1 = next(
                r for r in reports
                if r.event_id == diverged[0].id and r.language == "en" and r.version == 1
            )
            assert en_v1.superseded_by is not None

            # Forecast artifacts: alpha fitted, beta must have NONE (the
            # cross-tenant leak found this engagement makes this the
            # isolation assertion, and beta is the insufficient-history
            # rehearsal).
            alpha_models = (await s.execute(
                select(func.count()).select_from(ModelArtifact).where(
                    ModelArtifact.tenant_id == alpha.id
                )
            )).scalar_one()
            beta_models = (await s.execute(
                select(func.count()).select_from(ModelArtifact).where(
                    ModelArtifact.tenant_id == beta.id
                )
            )).scalar_one()
            assert alpha_models >= 1
            assert beta_models == 0
    finally:
        await wipe()


async def test_entry_point_runs_standalone_like_the_container(monkeypatch):
    """Regression for the first real staging run: `python -m
    app.scripts.build_staging_data` crashed with NoReferencedTableError
    (users.bar_id → bars) because the script's lazy model imports left
    SQLAlchemy's registry incomplete at flush time. The in-process tests
    could never catch it — pytest's collection imports the full model
    registry before build() runs. This test exercises the ACTUAL entry
    point in a fresh interpreter, exactly as the container invokes it."""
    import os as _os
    import subprocess
    import sys

    env = dict(_os.environ)
    env.update({
        "ENVIRONMENT": "staging",
        "POS_ADAPTER": "fake",
        "SLESH_API_TOKEN": "",   # env beats .env for pydantic-settings
        "SLESH_BRAND_ID": "",
    })
    proc = subprocess.run(
        [sys.executable, "-m", "app.scripts.build_staging_data", "--fast"],
        capture_output=True, text=True, env=env, timeout=600,
    )
    try:
        assert proc.returncode == 0, (
            f"entry point failed standalone (exit {proc.returncode}):\n"
            f"stderr tail:\n{proc.stderr[-2000:]}"
        )
        assert "staging data built" in proc.stdout
        assert await _tenant_count() == 2
    finally:
        _arm_staging_markers(monkeypatch)
        from app.scripts.build_staging_data import wipe
        await wipe()


async def test_live_event_ingests_end_to_end_and_history_has_no_line_errors(monkeypatch):
    """Staging Day-4 live failure: every live-event order raised
    BarNotInEventError because bar resolution is tenant-scoped
    (order_ingester._find_bar_by_slesh_id has no event filter, LIMIT 1),
    and the generator had mapped the SAME shop ids on four events at
    once — resolution was arbitrary. This test demands what the staging
    worker needs: a generated live event that actually ingests orders,
    and a history built with ZERO per-line errors on every event — not
    merely rows existing somewhere."""
    from datetime import datetime, timedelta

    from app.modules.events.models import Event, EventOrder, EventStatus
    from app.modules.pos.adapters.fake import LOCAL_TZ, FakePOSAdapter
    from app.modules.pos.order_ingester import _LookupCache, ingest_order
    from app.modules.stock_transactions.models import StockTransaction
    from app.modules.stock_transactions.service import StockTransactionService
    from app.scripts.build_staging_data import build, wipe

    _arm_staging_markers(monkeypatch)
    try:
        summary = await build(fast=True)
        # The generator's own history must be clean: a single per-line
        # error means some event's bars resolved to another event.
        assert summary["lines_errors"] == 0, summary
        assert summary["lines_ingested"] > 0

        async with TestSessionLocal() as s:
            from app.modules.auth.models import Tenant

            alpha = (await s.execute(
                select(Tenant).where(Tenant.slug == "staging-alpha")
            )).scalar_one()
            completed = (await s.execute(
                select(Event).where(
                    Event.tenant_id == alpha.id,
                    Event.status == EventStatus.COMPLETED,
                )
            )).scalars().all()
            # EVERY completed event has stock lines — not just whichever
            # event happened to win the ambiguous bar lookup.
            for e in completed:
                st_count = (await s.execute(
                    select(func.count()).select_from(StockTransaction).where(
                        StockTransaction.event_id == e.id,
                    )
                )).scalar_one()
                assert st_count > 0, f"{e.name}: no stock lines ingested"

            live = (await s.execute(
                select(Event).where(
                    Event.tenant_id == alpha.id,
                    Event.status == EventStatus.LIVE,
                )
            )).scalar_one()

            # Ingest a fresh window into the LIVE event through the real
            # pipeline — the exact thing the staging worker does per minute.
            window_start = (datetime.now(LOCAL_TZ) - timedelta(days=1)).replace(
                hour=18, minute=0, second=0, microsecond=0,
            )
            service = StockTransactionService(s)
            cache = _LookupCache()
            ingested = errors = 0
            async with FakePOSAdapter() as adapter:
                async for order in adapter.list_orders(
                    window_start, window_start + timedelta(minutes=5),
                    order_type=None,
                ):
                    r = await ingest_order(
                        db=s, order=order, event_id=live.id,
                        tenant_id=alpha.id, service=service, cache=cache,
                    )
                    ingested += r.lines_ingested
                    errors += r.lines_errors
            await s.commit()

            assert errors == 0, "live-event ingestion must not raise per line"
            assert ingested > 0, "at least one live-event line must ingest"
            live_eo = (await s.execute(
                select(func.count()).select_from(EventOrder).where(
                    EventOrder.event_id == live.id,
                )
            )).scalar_one()
            assert live_eo > 0
            live_st = (await s.execute(
                select(StockTransaction).where(
                    StockTransaction.event_id == live.id,
                    StockTransaction.bar_stock_id.is_not(None),
                ).limit(1)
            )).scalars().first()
            assert live_st is not None, (
                "live-event stock lines must decrement bar_stock so the "
                "depletion evaluator has burn rates"
            )
    finally:
        await wipe()


async def test_wipe_removes_event_orders_and_rerun_is_consistent(monkeypatch):
    """Day-5 finding: 28,178 orphaned event_orders accumulated across
    three days of regenerates (30,201 in local dev from test runs). The
    wipe relied on tenant-FK cascade — but event_orders is the ONE
    tenant-scoped table whose migration (eo1) created NO foreign keys at
    all (model/migration drift: the ORM declares CASCADE FKs the
    database does not have). Every regenerate therefore left the
    previous generation's orders behind, which is also what produced the
    mixed user.id/user._id state across close-together runs.

    wipe() must delete the generator tenants' event_orders explicitly,
    and a rerun must leave exactly one generation's rows."""
    from sqlalchemy import text

    from app.modules.auth.models import Tenant
    from app.scripts.build_staging_data import build, wipe

    _arm_staging_markers(monkeypatch)
    try:
        await build(fast=True)
        async with TestSessionLocal() as s:
            gen1_tenant_ids = [str(t) for t in (await s.execute(
                select(Tenant.id).where(Tenant.slug.in_(GENERATOR_SLUGS))
            )).scalars()]
            gen1_orders = (await s.execute(text(
                "SELECT count(*) FROM event_orders WHERE tenant_id::text = ANY(:tids)"
            ), {"tids": gen1_tenant_ids})).scalar_one()
            assert gen1_orders > 100, "generation 1 must have ingested orders"

        # Rebuild (build() wipes first). Generation 1's rows must be GONE.
        await build(fast=True)
        async with TestSessionLocal() as s:
            leftover = (await s.execute(text(
                "SELECT count(*) FROM event_orders WHERE tenant_id::text = ANY(:tids)"
            ), {"tids": gen1_tenant_ids})).scalar_one()
            assert leftover == 0, (
                f"{leftover} event_orders rows from the previous generation "
                "survived the wipe — the exact orphan-accumulation bug"
            )
            gen2_tenant_ids = [str(t) for t in (await s.execute(
                select(Tenant.id).where(Tenant.slug.in_(GENERATOR_SLUGS))
            )).scalars()]
            gen2_orders = (await s.execute(text(
                "SELECT count(*) FROM event_orders WHERE tenant_id::text = ANY(:tids)"
            ), {"tids": gen2_tenant_ids})).scalar_one()
            assert gen2_orders > 100, "generation 2 must have its own orders"

        # And a bare wipe leaves zero generator-owned orders behind.
        await wipe()
        async with TestSessionLocal() as s:
            after = (await s.execute(text(
                "SELECT count(*) FROM event_orders WHERE tenant_id::text = ANY(:tids)"
            ), {"tids": gen2_tenant_ids})).scalar_one()
            assert after == 0
    finally:
        await wipe()
