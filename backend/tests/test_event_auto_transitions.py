"""Tests for cron_auto_transition_event_statuses.

The cron orchestrates DRAFT/ACTIVE/LIVE event transitions based on
scheduled_at + scheduled_end_at vs now(). Tests verify:

  1. DRAFT past scheduled_at  -> activated + started (status LIVE)
  2. ACTIVE past scheduled_at -> started (status LIVE)
  3. DRAFT before scheduled_at -> no-op (status DRAFT)
  4. LIVE past scheduled_end_at, NO recent tx -> COMPLETED
  5. LIVE past scheduled_end_at, WITH recent tx -> stays LIVE
     (60-min silence guard fires)

Uses the SAVEPOINT db_session fixture so xproject_dev is never
mutated. The cron internally calls async_session_factory(); we
monkey-patch it to return the SAVEPOINT-bound session.

Spec: S3 of docs/e2e-validation-design.md, locked 2026-06-01.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Tenant
from app.modules.bars.models import Bar
from app.modules.events.models import Event, EventStatus
from app.modules.products.models import Product, ProductCategory, ProductType, ProductUnit
from app.modules.stock_transactions.models import (
    StockTransaction,
    TransactionSource,
)
from app.modules.venues.models import Venue
from app.workers import tasks as tasks_module
from app.workers.tasks import cron_auto_transition_event_statuses


# ─── Helpers ────────────────────────────────────────────────────────

async def _get_tenant(db: AsyncSession) -> Tenant:
    r = await db.execute(select(Tenant).where(Tenant.slug == "noma-group"))
    return r.scalar_one()


async def _make_venue(db: AsyncSession, tenant_id) -> Venue:
    v = Venue(tenant_id=tenant_id, name=f"V-{uuid4().hex[:8]}", address="-")
    db.add(v)
    await db.flush()
    return v


async def _park_existing_live(db: AsyncSession, tenant_id) -> None:
    """Demote any currently-LIVE event for this tenant to DRAFT.

    xproject_dev has Sundance 2026 status=LIVE all the time. Tests
    that need to create a SECOND live event hit the
    one_live_event_per_tenant unique index. We demote within the
    SAVEPOINT scope; rollback at test end restores LIVE status
    automatically.
    """
    r = await db.execute(
        select(Event).where(
            Event.tenant_id == tenant_id,
            Event.status == EventStatus.LIVE,
        )
    )
    for live_ev in r.scalars().all():
        live_ev.status = EventStatus.DRAFT
    await db.flush()


async def _make_event(
    db: AsyncSession, tenant_id, venue_id,
    *, status: EventStatus, scheduled_at: datetime, scheduled_end_at: datetime,
) -> Event:
    ev = Event(
        tenant_id=tenant_id,
        venue_id=venue_id,
        name=f"E-{uuid4().hex[:8]}",
        scheduled_at=scheduled_at,
        scheduled_end_at=scheduled_end_at,
        status=status,
        expected_guest_count=100,
        version=1,
    )
    if status == EventStatus.LIVE:
        ev.started_at = scheduled_at  # arbitrary but plausible
    db.add(ev)
    await db.flush()
    return ev


async def _make_bar(db: AsyncSession, tenant_id, event_id) -> Bar:
    b = Bar(
        tenant_id=tenant_id, event_id=event_id,
        name=f"B-{uuid4().hex[:8]}", bar_type="drinks", is_active=True,
    )
    db.add(b)
    await db.flush()
    return b


async def _make_product(db: AsyncSession, tenant_id) -> Product:
    p = Product(
        tenant_id=tenant_id,
        name=f"P-{uuid4().hex[:8]}",
        product_type=ProductType.DRINK,
        category=ProductCategory.BASIC_COCKTAIL,
        unit=ProductUnit.GLASS,
        default_price_cents=1000,
        tier_rank=2,
    )
    db.add(p)
    await db.flush()
    return p


async def _make_stock_tx(
    db: AsyncSession, tenant_id, event_id, bar_id, product_id,
    *, created_at: datetime,
) -> StockTransaction:
    """Create a StockTransaction at a SPECIFIC time (for the silence guard test)."""
    tx = StockTransaction(
        tenant_id=tenant_id,
        event_id=event_id,
        bar_id=bar_id,
        product_id=product_id,
        qty=Decimal("1.000"),
        deficit_qty=Decimal("0.000"),
        source=TransactionSource.SLESH_POS,
        source_idempotency_key=f"test-{uuid4().hex[:8]}",
    )
    db.add(tx)
    await db.flush()
    # Manually set created_at to override server-default NOW().
    tx.created_at = created_at
    await db.flush()
    return tx


@pytest.fixture
def patched_session_factory(db_session: AsyncSession, monkeypatch):
    """Patch async_session_factory so the cron uses our SAVEPOINT session.

    The cron does `async with async_session_factory() as session: ...`
    which would normally open a fresh connection bypassing our isolation.
    We replace it with a no-op async context manager that yields the
    test session.
    """
    class _SessionWrapper:
        async def __aenter__(self):
            return db_session
        async def __aexit__(self, *args):
            # Do NOT close — outer SAVEPOINT teardown handles it.
            return None

    monkeypatch.setattr(
        tasks_module, "async_session_factory",
        lambda: _SessionWrapper(),
    )
    return db_session


# ─── Tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_draft_past_scheduled_at_promoted_to_live(
    db_session: AsyncSession, patched_session_factory,
):
    """DRAFT event whose scheduled_at has passed should auto-activate AND
    start, ending up LIVE."""
    now = datetime.now(timezone.utc)
    tenant = await _get_tenant(db_session)
    await _park_existing_live(db_session, tenant.id)
    venue = await _make_venue(db_session, tenant.id)
    event = await _make_event(
        db_session, tenant.id, venue.id,
        status=EventStatus.DRAFT,
        scheduled_at=now - timedelta(minutes=10),
        scheduled_end_at=now + timedelta(hours=4),
    )

    result = await cron_auto_transition_event_statuses(ctx={})

    assert result["status"] == "ok"
    assert result["activated"] >= 1
    assert result["started"] >= 1

    await db_session.refresh(event)
    assert event.status == EventStatus.LIVE
    assert event.started_at is not None


@pytest.mark.asyncio
async def test_active_past_scheduled_at_promoted_to_live(
    db_session: AsyncSession, patched_session_factory,
):
    """ACTIVE event whose scheduled_at has passed should auto-start
    (single transition, not activated)."""
    now = datetime.now(timezone.utc)
    tenant = await _get_tenant(db_session)
    await _park_existing_live(db_session, tenant.id)
    venue = await _make_venue(db_session, tenant.id)
    event = await _make_event(
        db_session, tenant.id, venue.id,
        status=EventStatus.ACTIVE,
        scheduled_at=now - timedelta(minutes=10),
        scheduled_end_at=now + timedelta(hours=4),
    )

    result = await cron_auto_transition_event_statuses(ctx={})

    assert result["status"] == "ok"
    assert result["started"] >= 1
    # Activated counter should NOT be bumped — event was already ACTIVE.

    await db_session.refresh(event)
    assert event.status == EventStatus.LIVE
    assert event.started_at is not None


@pytest.mark.asyncio
async def test_draft_before_scheduled_at_is_no_op(
    db_session: AsyncSession, patched_session_factory,
):
    """DRAFT event whose scheduled_at is in the FUTURE should be untouched."""
    now = datetime.now(timezone.utc)
    tenant = await _get_tenant(db_session)
    venue = await _make_venue(db_session, tenant.id)
    event = await _make_event(
        db_session, tenant.id, venue.id,
        status=EventStatus.DRAFT,
        scheduled_at=now + timedelta(hours=1),
        scheduled_end_at=now + timedelta(hours=5),
    )

    result = await cron_auto_transition_event_statuses(ctx={})

    assert result["status"] == "ok"
    # No promotion should have happened for THIS event.
    # (Other test events from prior cases may have triggered counters;
    # we assert on the event state directly.)

    await db_session.refresh(event)
    assert event.status == EventStatus.DRAFT
    assert event.started_at is None


@pytest.mark.asyncio
async def test_live_past_end_no_recent_tx_completes(
    db_session: AsyncSession, patched_session_factory,
):
    """LIVE event past scheduled_end_at with no recent tx should auto-end."""
    now = datetime.now(timezone.utc)
    tenant = await _get_tenant(db_session)
    await _park_existing_live(db_session, tenant.id)
    venue = await _make_venue(db_session, tenant.id)
    event = await _make_event(
        db_session, tenant.id, venue.id,
        status=EventStatus.LIVE,
        scheduled_at=now - timedelta(hours=5),
        scheduled_end_at=now - timedelta(hours=1),
    )

    result = await cron_auto_transition_event_statuses(ctx={})

    assert result["status"] == "ok"
    assert result["completed"] >= 1

    await db_session.refresh(event)
    assert event.status == EventStatus.COMPLETED
    assert event.ended_at is not None


@pytest.mark.asyncio
async def test_live_past_end_with_recent_tx_stays_live(
    db_session: AsyncSession, patched_session_factory,
):
    """LIVE event past scheduled_end_at BUT with a recent stock tx (within
    60min) should stay LIVE — the silence guard prevents premature end."""
    now = datetime.now(timezone.utc)
    tenant = await _get_tenant(db_session)
    await _park_existing_live(db_session, tenant.id)
    venue = await _make_venue(db_session, tenant.id)
    event = await _make_event(
        db_session, tenant.id, venue.id,
        status=EventStatus.LIVE,
        scheduled_at=now - timedelta(hours=5),
        scheduled_end_at=now - timedelta(minutes=30),
    )
    bar = await _make_bar(db_session, tenant.id, event.id)
    product = await _make_product(db_session, tenant.id)
    # Inject a tx from 10 minutes ago (well within 60-min window)
    await _make_stock_tx(
        db_session, tenant.id, event.id, bar.id, product.id,
        created_at=now - timedelta(minutes=10),
    )

    result = await cron_auto_transition_event_statuses(ctx={})

    assert result["status"] == "ok"
    assert result["skipped_silence"] >= 1

    await db_session.refresh(event)
    assert event.status == EventStatus.LIVE, (
        "Event should NOT be ended — recent tx within 60min "
        "(silence guard prevents premature auto-end)"
    )
    assert event.ended_at is None
