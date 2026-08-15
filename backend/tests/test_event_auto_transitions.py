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
from tests.fixtures.alerts.factories import make_tenant


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


async def _park_other_due_events(db: AsyncSession, tenant_id) -> None:
    """Push every OTHER due DRAFT/ACTIVE event for this tenant far into
    the future, so it can't compete with (or block) the event a test is
    about to create.

    xproject_dev has a pile of leftover stale DRAFT events for this
    tenant from old debug/seed scripts, all with scheduled_at in the
    past. Without this, the cron picks them up in the SAME tick as the
    test's own event; whichever one the (now-deterministic, ORDER BY
    scheduled_at) query happens to process first wins the one-live-per-
    tenant slot, and it isn't guaranteed to be the test's own event —
    the test's own event can then legitimately, non-crashingly fail to
    reach LIVE by conflicting with a stale event the test never created
    or asserted on. Same SAVEPOINT-scoped, auto-restored-at-teardown
    pattern as _park_existing_live above — nothing here touches real
    xproject_dev data past this test's rollback.
    """
    now = datetime.now(timezone.utc)
    r = await db.execute(
        select(Event).where(
            Event.tenant_id == tenant_id,
            Event.status.in_([EventStatus.DRAFT, EventStatus.ACTIVE]),
            Event.scheduled_at <= now,
        )
    )
    for ev in r.scalars().all():
        # Move both fields — ck_events_scheduled_end_after_start requires
        # scheduled_end_at > scheduled_at, and only moving scheduled_at
        # can violate it if the stale row's original scheduled_end_at is
        # earlier than the new scheduled_at.
        ev.scheduled_at = now + timedelta(days=365)
        ev.scheduled_end_at = now + timedelta(days=365, hours=4)
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


@pytest.fixture
def patched_isolated_session_factory(db_session: AsyncSession, monkeypatch):
    """Like patched_session_factory, but each async_session_factory() call
    returns a GENUINELY SEPARATE AsyncSession — same underlying connection
    as db_session (so everything still rolls back inside db_session's
    outer SAVEPOINT-per-test transaction at teardown), but its own
    identity map, so a rollback on one of these sessions cannot expire
    ORM objects loaded by a different one.

    This is what F-02's fix actually needs to be exercised meaningfully:
    the whole point of the fix is "each event gets its own session," and
    patched_session_factory (which always hands back the literal same
    db_session object) can't distinguish "fixed" from "still shares one
    session" — a rollback on that single shared session would still expire
    everything, fix or no fix. Uses the same join_transaction_mode=
    "create_savepoint" idiom db_session itself is built on (see conftest.py)
    so each session's commit()/rollback() only affects its own SAVEPOINT.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    NestedSession = async_sessionmaker(
        bind=db_session._test_connection, expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    opened: list[AsyncSession] = []

    class _FreshSessionWrapper:
        async def __aenter__(self):
            session = NestedSession()
            opened.append(session)
            return session
        async def __aexit__(self, *args):
            # Close this one session — NOT db_session, whose outer
            # SAVEPOINT teardown (conftest.py) handles the real rollback.
            await opened[-1].close()
            return None

    monkeypatch.setattr(
        tasks_module, "async_session_factory",
        lambda: _FreshSessionWrapper(),
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
    await _park_other_due_events(db_session, tenant.id)
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
    await _park_other_due_events(db_session, tenant.id)
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


# ── F-02: one event's conflict must not poison the next event's session ──

@pytest.mark.asyncio
async def test_conflicting_event_does_not_poison_next_due_event(
    db_session: AsyncSession, patched_isolated_session_factory,
):
    """Two due events in the same tick. The first (tenant 1) conflicts
    with an already-LIVE event for its own tenant and fails with
    LiveEventConflictError. The second (tenant 2, unrelated) has no
    conflict and must still be correctly promoted to LIVE.

    Before F-02: both events were loaded via one shared session; the
    first event's failure handler called session.rollback(), which
    expired every ORM object the session was tracking — including the
    second event's not-yet-processed row. Its very next attribute
    access crashed with MissingGreenlet, uncaught, so it never even got
    a chance to transition. Needs patched_isolated_session_factory (not
    patched_session_factory) — this only proves anything if each event
    genuinely gets its own session, which is exactly what F-02 adds.
    """
    now = datetime.now(timezone.utc)

    # Tenant 1: a genuinely-live "blocker", plus a DRAFT event that will
    # conflict with it. Scheduled MORE overdue than tenant 2's event so
    # the due_events ORDER BY scheduled_at puts it first.
    tenant1 = await _get_tenant(db_session)
    await _park_existing_live(db_session, tenant1.id)
    venue1 = await _make_venue(db_session, tenant1.id)
    blocker = await _make_event(
        db_session, tenant1.id, venue1.id,
        status=EventStatus.LIVE,
        scheduled_at=now - timedelta(hours=2),
        scheduled_end_at=now + timedelta(hours=2),  # still genuinely live
    )
    conflicting = await _make_event(
        db_session, tenant1.id, venue1.id,
        status=EventStatus.DRAFT,
        scheduled_at=now - timedelta(minutes=20),
        scheduled_end_at=now + timedelta(hours=4),
    )

    # Tenant 2: unrelated, no conflict, less overdue -> processed second.
    tenant2 = await make_tenant(db_session)
    venue2 = await _make_venue(db_session, tenant2.id)
    clean = await _make_event(
        db_session, tenant2.id, venue2.id,
        status=EventStatus.DRAFT,
        scheduled_at=now - timedelta(minutes=10),
        scheduled_end_at=now + timedelta(hours=4),
    )

    result = await cron_auto_transition_event_statuses(ctx={})

    # No uncaught exception — the cron completed the whole tick.
    assert result["status"] == "ok"
    assert result["errors"] >= 1

    await db_session.refresh(conflicting)
    # activate_event (DRAFT->ACTIVE) has no conflict check and commits
    # before start_event's conflict check runs — so this event correctly
    # got as far as ACTIVE, then correctly failed to reach LIVE.
    assert conflicting.status == EventStatus.ACTIVE
    assert conflicting.started_at is None

    await db_session.refresh(clean)
    # The event that matters for this test: NOT poisoned by the earlier
    # failure, correctly promoted all the way to LIVE.
    assert clean.status == EventStatus.LIVE
    assert clean.started_at is not None

    await db_session.refresh(blocker)
    assert blocker.status == EventStatus.LIVE  # untouched
