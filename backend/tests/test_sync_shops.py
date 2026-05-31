"""Tests for sync_shops() — the Slesh→bars upsert pipeline.

Uses the db_session fixture (SAVEPOINT rollback) so every test runs
inside a transaction that auto-rolls back at end. xproject_dev is
never mutated.

Coverage:
  1. happy_path            — 3 new Slesh shops -> 3 bars created
  2. idempotent            — re-run with same shops -> all skipped
  3. rename                — Slesh name change -> bar.name updated
  4. disable_by_slesh      — Slesh isEnabled=false -> bar.is_active=False
  5. missing_from_slesh    — bar's slesh_id no longer in response ->
                              bar.is_active=False, deactivated counter += 1
  6. slesh_down            — adapter raises -> graceful no-op, DB untouched

Spec: BARS work item, May 27 2026 — Hesam/Omar bars-sync architecture.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterable
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Tenant
from app.modules.bars.models import Bar
from app.modules.events.models import Event, EventStatus
from app.modules.pos.schemas import Shop as SleshShop
from app.modules.pos.sync_service import sync_shops
from app.modules.venues.models import Venue


# ─── Test fakes ──────────────────────────────────────────────────────

class FakeAdapter:
    """Minimal SleshAdapter stand-in.

    Implements only the surface sync_shops() touches: an async
    list_shops() returning list[Shop]. We bypass the real HTTP path
    entirely.

    Pass `raise_on_call=True` to simulate a Slesh outage.
    """
    def __init__(self, shops: Iterable[SleshShop], *, raise_on_call: bool = False):
        self._shops = list(shops)
        self._raise = raise_on_call
        self.calls = 0

    async def list_shops(self, experience_id: str | None = None) -> list[SleshShop]:
        self.calls += 1
        if self._raise:
            raise RuntimeError("simulated Slesh outage")
        return list(self._shops)


def make_slesh_shop(
    *, id: str | None = None, name: str = "Test Shop",
    is_enabled: bool = True,
) -> SleshShop:
    """Build a Shop without hitting Slesh — Pydantic .model_validate handles aliases."""
    return SleshShop.model_validate({
        "_id":       id or uuid4().hex,
        "name":      name,
        "isEnabled": is_enabled,
    })


# ─── Helpers ─────────────────────────────────────────────────────────

async def _get_tenant(db: AsyncSession) -> Tenant:
    r = await db.execute(select(Tenant).where(Tenant.slug == "noma-group"))
    return r.scalar_one()


async def _create_venue(db: AsyncSession, tenant_id) -> Venue:
    v = Venue(tenant_id=tenant_id, name=f"V-{uuid4().hex[:8]}", address="-")
    db.add(v)
    await db.flush()
    return v


async def _create_event(db: AsyncSession, tenant_id, venue_id) -> Event:
    ev = Event(
        tenant_id=tenant_id,
        venue_id=venue_id,
        name=f"E-{uuid4().hex[:8]}",
        scheduled_date=date(2026, 6, 19),
        status=EventStatus.DRAFT,  # DRAFT avoids the one-LIVE-per-tenant constraint
        expected_guest_count=1000,
        started_at=datetime.now(timezone.utc),
        version=1,
    )
    db.add(ev)
    await db.flush()
    return ev


async def _create_existing_bar(
    db: AsyncSession, tenant_id, event_id,
    *, name: str, slesh_id: str | None, is_active: bool = True,
) -> Bar:
    bar = Bar(
        tenant_id=tenant_id,
        event_id=event_id,
        name=name,
        slesh_negozio_id=slesh_id,
        bar_type="drinks",
        is_active=is_active,
    )
    db.add(bar)
    await db.flush()
    return bar


async def _count_bars(db: AsyncSession, event_id, *, only_active: bool = False) -> int:
    stmt = select(Bar).where(Bar.event_id == event_id)
    if only_active:
        stmt = stmt.where(Bar.is_active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return len(rows)


# ─── 1. happy path ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_path_three_new_shops_create_three_bars(
    db_session: AsyncSession,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)

    shops = [
        make_slesh_shop(name="Cocktail Bar"),
        make_slesh_shop(name="Wine Garden"),
        make_slesh_shop(name="Beer Stand"),
    ]
    adapter = FakeAdapter(shops)

    result = await sync_shops(
        db=db_session, adapter=adapter,
        tenant_id=tenant.id, event_id=event.id,
    )

    assert adapter.calls == 1
    assert result.created == 3
    assert result.updated == 0
    assert result.skipped == 0
    assert result.deactivated == 0
    assert await _count_bars(db_session, event.id) == 3


# ─── 2. idempotent ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_idempotent_rerun_skips_all(db_session: AsyncSession):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)

    shops = [
        make_slesh_shop(id="s-1", name="Cocktail Bar"),
        make_slesh_shop(id="s-2", name="Wine Garden"),
    ]

    # First run: creates
    r1 = await sync_shops(
        db=db_session, adapter=FakeAdapter(shops),
        tenant_id=tenant.id, event_id=event.id,
    )
    assert r1.created == 2

    # Second run: all skipped
    r2 = await sync_shops(
        db=db_session, adapter=FakeAdapter(shops),
        tenant_id=tenant.id, event_id=event.id,
    )
    assert r2.created == 0
    assert r2.updated == 0
    assert r2.skipped == 2
    assert r2.deactivated == 0
    assert await _count_bars(db_session, event.id) == 2


# ─── 3. rename ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slesh_renames_shop_then_bar_name_updates(db_session: AsyncSession):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)

    # Seed: bar already exists with old name
    await _create_existing_bar(
        db_session, tenant.id, event.id,
        name="Old Name", slesh_id="s-rename-1",
    )

    shops = [make_slesh_shop(id="s-rename-1", name="New Cool Name")]

    result = await sync_shops(
        db=db_session, adapter=FakeAdapter(shops),
        tenant_id=tenant.id, event_id=event.id,
    )

    assert result.updated == 1
    assert result.created == 0

    # Verify the name on the row
    r = await db_session.execute(
        select(Bar).where(Bar.slesh_negozio_id == "s-rename-1")
    )
    bar = r.scalar_one()
    assert bar.name == "New Cool Name"


# ─── 4. disable by Slesh ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slesh_disables_shop_then_bar_becomes_inactive(
    db_session: AsyncSession,
):
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)

    await _create_existing_bar(
        db_session, tenant.id, event.id,
        name="Soon Disabled", slesh_id="s-disable-1", is_active=True,
    )

    shops = [make_slesh_shop(id="s-disable-1", name="Soon Disabled", is_enabled=False)]

    result = await sync_shops(
        db=db_session, adapter=FakeAdapter(shops),
        tenant_id=tenant.id, event_id=event.id,
    )

    assert result.updated == 1
    assert result.deactivated == 0  # this is the Slesh-says-disabled path,
                                     # NOT the missing-from-Slesh path

    r = await db_session.execute(
        select(Bar).where(Bar.slesh_negozio_id == "s-disable-1")
    )
    bar = r.scalar_one()
    assert bar.is_active is False


# ─── 5. missing from Slesh response ────────────────────────────────

@pytest.mark.asyncio
async def test_bar_missing_from_slesh_response_gets_deactivated(
    db_session: AsyncSession,
):
    """The Wine Station case: bar exists locally with a slesh_negozio_id
    but Slesh no longer reports that shop. We deactivate, never delete."""
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)

    # Seed: existing bar that USED to be in Slesh
    await _create_existing_bar(
        db_session, tenant.id, event.id,
        name="Wine Station", slesh_id="s-missing-1", is_active=True,
    )

    # Slesh now reports only a different shop
    shops = [make_slesh_shop(id="s-other", name="Some Other Bar")]

    result = await sync_shops(
        db=db_session, adapter=FakeAdapter(shops),
        tenant_id=tenant.id, event_id=event.id,
    )

    assert result.created == 1     # the new shop
    assert result.deactivated == 1 # Wine Station

    r = await db_session.execute(
        select(Bar).where(Bar.slesh_negozio_id == "s-missing-1")
    )
    bar = r.scalar_one()
    assert bar.is_active is False, "missing-from-Slesh should set is_active=False"
    # Not deleted — row still exists, FK chains preserved
    assert bar.name == "Wine Station"  # name preserved too


# ─── 6. Slesh adapter raises ────────────────────────────────────────

@pytest.mark.asyncio
async def test_slesh_outage_propagates_no_db_changes(db_session: AsyncSession):
    """If the adapter call fails, sync_shops should not silently swallow it.
    The exception propagates and the caller (cron_sync_bars_from_slesh)
    handles the rollback. Here we just verify nothing partial was written.
    """
    tenant = await _get_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_event(db_session, tenant.id, venue.id)

    # Seed a bar that should NOT be touched if the call fails
    await _create_existing_bar(
        db_session, tenant.id, event.id,
        name="Untouched", slesh_id="s-keep-1", is_active=True,
    )

    adapter = FakeAdapter([], raise_on_call=True)

    with pytest.raises(RuntimeError, match="simulated Slesh outage"):
        await sync_shops(
            db=db_session, adapter=adapter,
            tenant_id=tenant.id, event_id=event.id,
        )

    # Bar should be exactly as we left it
    r = await db_session.execute(
        select(Bar).where(Bar.slesh_negozio_id == "s-keep-1")
    )
    bar = r.scalar_one()
    assert bar.is_active is True
    assert bar.name == "Untouched"
