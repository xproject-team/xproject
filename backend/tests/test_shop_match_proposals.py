"""Tests for SleshShopMatchProposal — fuzzy matching, state machine,
and sync_shops integration.

Covers the critical paths for Sundance:
  - Service: propose_for_shops creates one row per unmatched shop
  - Service: best fuzzy match selected from unlinked bars
  - Service: accept/reject/skip state machine
  - Sync: integration with sync_shops (creates proposals, dedups
    on re-run, never auto-creates bars)

Uses the SAVEPOINT db_session fixture for isolation.

See docs/e2e-validation-design.md (S4 — Name-matching UX).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Tenant, User
from app.modules.bars.models import Bar
from app.modules.events.models import Event, EventStatus
from app.modules.pos.models import SleshShopMatchProposal, ShopMatchStatus
from app.modules.pos.proposals_service import (
    AcceptRequiresBarError,
    ProposalAlreadyDecidedError,
    ShopMatchProposalsService,
)
from app.modules.pos.sync_service import sync_shops
from app.modules.venues.models import Venue


# ─── Helpers ────────────────────────────────────────────────────────


class _MockSleshShop:
    """Stand-in for app.modules.pos.schemas.Shop without going through
    the Slesh adapter. Has the fields the sync code reads."""
    def __init__(self, id: str, name: str, is_enabled: bool = True):
        self.id = id
        self.name = name
        self.is_enabled = is_enabled


class _MockAdapter:
    """Stand-in for SleshAdapter — sync_shops only calls list_shops."""
    def __init__(self, shops: list[_MockSleshShop]):
        self._shops = shops
    async def list_shops(self, *, experience_id=None):
        return self._shops


async def _get_tenant(db: AsyncSession) -> Tenant:
    r = await db.execute(select(Tenant).where(Tenant.slug == "noma-group"))
    return r.scalar_one()


async def _get_user(db: AsyncSession, tenant_id) -> User:
    """Pick the owner (Omar) for decided_by_user_id stamps."""
    r = await db.execute(
        select(User).where(User.tenant_id == tenant_id).limit(1)
    )
    return r.scalar_one()


async def _make_venue(db: AsyncSession, tenant_id) -> Venue:
    v = Venue(tenant_id=tenant_id, name=f"V-{uuid4().hex[:8]}", address="-")
    db.add(v); await db.flush()
    return v


async def _make_event(db: AsyncSession, tenant_id, venue_id) -> Event:
    now = datetime.now(timezone.utc)
    ev = Event(
        tenant_id=tenant_id,
        venue_id=venue_id,
        name=f"E-{uuid4().hex[:8]}",
        scheduled_at=now,
        scheduled_end_at=now.replace(year=now.year + 1),
        status=EventStatus.DRAFT,
        expected_guest_count=100,
        version=1,
    )
    db.add(ev); await db.flush()
    return ev


async def _make_bar(db, tenant_id, event_id, name, slesh_id=None) -> Bar:
    b = Bar(
        tenant_id=tenant_id,
        event_id=event_id,
        name=name,
        slesh_negozio_id=slesh_id,
        bar_type="drinks",
        is_active=True,
    )
    db.add(b); await db.flush()
    return b


# ─── Group A — Service tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_propose_creates_one_proposal_per_unmatched_shop(
    db_session: AsyncSession,
):
    """propose_for_shops should create exactly one pending proposal
    per shop with no matching bar linkage."""
    tenant = await _get_tenant(db_session)
    venue = await _make_venue(db_session, tenant.id)
    event = await _make_event(db_session, tenant.id, venue.id)
    # 1 unlinked bar to match against
    await _make_bar(db_session, tenant.id, event.id, "Cocktail Bar")

    shops = [
        _MockSleshShop("slesh-1", "Cocktail Bar"),
        _MockSleshShop("slesh-2", "Beer Bar"),
        _MockSleshShop("slesh-3", "Malandrino"),
    ]

    service = ShopMatchProposalsService(db_session)
    proposals = await service.propose_for_shops(
        tenant_id=tenant.id, event_id=event.id, unmatched_shops=shops,
    )

    assert len(proposals) == 3
    statuses = {p.status for p in proposals}
    assert statuses == {ShopMatchStatus.PENDING}


@pytest.mark.asyncio
async def test_propose_finds_best_fuzzy_match_among_unlinked_bars(
    db_session: AsyncSession,
):
    """The best fuzzy match (by name similarity) should be on
    suggested_bar_id. Other unlinked bars are candidates but only
    one wins per proposal."""
    tenant = await _get_tenant(db_session)
    venue = await _make_venue(db_session, tenant.id)
    event = await _make_event(db_session, tenant.id, venue.id)

    cocktail_bar = await _make_bar(db_session, tenant.id, event.id, "Cocktail Bar")
    beer_bar     = await _make_bar(db_session, tenant.id, event.id, "Beer Bar")
    malandrino   = await _make_bar(db_session, tenant.id, event.id, "Malandrino")

    # Slesh shop name should fuzzy-match Beer Bar
    shops = [_MockSleshShop("slesh-1", "  BEER BAR  ")]

    service = ShopMatchProposalsService(db_session)
    proposals = await service.propose_for_shops(
        tenant_id=tenant.id, event_id=event.id, unmatched_shops=shops,
    )

    assert len(proposals) == 1
    p = proposals[0]
    assert p.suggested_bar_id == beer_bar.id, (
        f"Expected suggested_bar_id to match 'Beer Bar' ({beer_bar.id}), "
        f"got {p.suggested_bar_id}"
    )
    assert p.similarity_score == Decimal("1.000")  # whitespace + case normalized


@pytest.mark.asyncio
async def test_accept_links_bar_and_marks_decision(
    db_session: AsyncSession,
):
    """Accepting a proposal sets bar.slesh_negozio_id and stamps
    the decision on the proposal row."""
    tenant = await _get_tenant(db_session)
    user   = await _get_user(db_session, tenant.id)
    venue  = await _make_venue(db_session, tenant.id)
    event  = await _make_event(db_session, tenant.id, venue.id)
    bar    = await _make_bar(db_session, tenant.id, event.id, "Cocktail Bar")

    service = ShopMatchProposalsService(db_session)
    proposals = await service.propose_for_shops(
        tenant_id=tenant.id, event_id=event.id,
        unmatched_shops=[_MockSleshShop("slesh-CB", "Cocktail Bar")],
    )
    proposal = proposals[0]
    assert proposal.suggested_bar_id == bar.id

    # Accept (suggested_bar_id used since no override)
    accepted = await service.accept(
        tenant_id=tenant.id, proposal_id=proposal.id, user_id=user.id,
    )

    # Proposal: stamped + ACCEPTED
    assert accepted.status == ShopMatchStatus.ACCEPTED
    assert accepted.decided_at is not None
    assert accepted.decided_by_user_id == user.id

    # Bar: now linked to the Slesh shop ID
    await db_session.refresh(bar)
    assert bar.slesh_negozio_id == "slesh-CB"


@pytest.mark.asyncio
async def test_accept_without_suggestion_or_override_raises(
    db_session: AsyncSession,
):
    """If proposal has no suggested_bar_id AND no override provided,
    accept must raise AcceptRequiresBarError."""
    tenant = await _get_tenant(db_session)
    user   = await _get_user(db_session, tenant.id)
    venue  = await _make_venue(db_session, tenant.id)
    event  = await _make_event(db_session, tenant.id, venue.id)
    # No bars exist => no fuzzy candidate => suggested_bar_id will be NULL

    service = ShopMatchProposalsService(db_session)
    proposals = await service.propose_for_shops(
        tenant_id=tenant.id, event_id=event.id,
        unmatched_shops=[_MockSleshShop("slesh-X", "Some New Bar")],
    )
    assert proposals[0].suggested_bar_id is None

    with pytest.raises(AcceptRequiresBarError):
        await service.accept(
            tenant_id=tenant.id, proposal_id=proposals[0].id, user_id=user.id,
        )


@pytest.mark.asyncio
async def test_reject_marks_decision_and_does_not_link_bar(
    db_session: AsyncSession,
):
    """Rejecting stamps the proposal as REJECTED and leaves bars untouched."""
    tenant = await _get_tenant(db_session)
    user   = await _get_user(db_session, tenant.id)
    venue  = await _make_venue(db_session, tenant.id)
    event  = await _make_event(db_session, tenant.id, venue.id)
    bar    = await _make_bar(db_session, tenant.id, event.id, "Cocktail Bar")

    service = ShopMatchProposalsService(db_session)
    proposals = await service.propose_for_shops(
        tenant_id=tenant.id, event_id=event.id,
        unmatched_shops=[_MockSleshShop("slesh-CB", "Cocktail Bar")],
    )
    rejected = await service.reject(
        tenant_id=tenant.id, proposal_id=proposals[0].id, user_id=user.id,
    )

    assert rejected.status == ShopMatchStatus.REJECTED
    assert rejected.decided_at is not None

    # Bar must NOT have been linked
    await db_session.refresh(bar)
    assert bar.slesh_negozio_id is None


# ─── Group B — sync_shops integration ───────────────────────────────


@pytest.mark.asyncio
async def test_sync_shops_with_unmatched_shop_creates_proposal(
    db_session: AsyncSession,
):
    """End-to-end: sync_shops should create a proposal (not a new bar)
    when it sees a shop with no matching slesh_negozio_id."""
    tenant = await _get_tenant(db_session)
    venue  = await _make_venue(db_session, tenant.id)
    event  = await _make_event(db_session, tenant.id, venue.id)
    # Existing unlinked bar
    await _make_bar(db_session, tenant.id, event.id, "Cocktail Bar")

    initial_bar_count = (await db_session.execute(
        select(Bar).where(Bar.event_id == event.id)
    )).scalars().all()
    assert len(initial_bar_count) == 1

    adapter = _MockAdapter(shops=[_MockSleshShop("slesh-CB", "Cocktail Bar")])
    result = await sync_shops(
        db=db_session, adapter=adapter,
        tenant_id=tenant.id, event_id=event.id,
    )

    # No new bars created
    bars_after = (await db_session.execute(
        select(Bar).where(Bar.event_id == event.id)
    )).scalars().all()
    assert len(bars_after) == 1, "sync_shops must not auto-create bars"
    assert result.created == 0
    assert result.proposals_created == 1

    # Proposal exists
    proposal = (await db_session.execute(
        select(SleshShopMatchProposal).where(
            SleshShopMatchProposal.event_id == event.id,
            SleshShopMatchProposal.slesh_shop_id == "slesh-CB",
        )
    )).scalar_one()
    assert proposal.status == ShopMatchStatus.PENDING


@pytest.mark.asyncio
async def test_sync_shops_rerun_does_not_duplicate_proposals(
    db_session: AsyncSession,
):
    """Re-running sync with the same Slesh shop must NOT create
    a duplicate proposal (unique constraint enforced)."""
    tenant = await _get_tenant(db_session)
    venue  = await _make_venue(db_session, tenant.id)
    event  = await _make_event(db_session, tenant.id, venue.id)
    await _make_bar(db_session, tenant.id, event.id, "Cocktail Bar")

    adapter = _MockAdapter(shops=[_MockSleshShop("slesh-CB", "Cocktail Bar")])

    # First sync — proposal created
    r1 = await sync_shops(
        db=db_session, adapter=adapter,
        tenant_id=tenant.id, event_id=event.id,
    )
    assert r1.proposals_created == 1

    # Second sync — same shop — proposal NOT recreated
    r2 = await sync_shops(
        db=db_session, adapter=adapter,
        tenant_id=tenant.id, event_id=event.id,
    )
    assert r2.proposals_created == 0, (
        "Re-syncing with the same Slesh shop must not create a "
        "duplicate proposal (unique constraint should hold)"
    )

    # Only 1 row in DB
    rows = (await db_session.execute(
        select(SleshShopMatchProposal).where(
            SleshShopMatchProposal.event_id == event.id,
        )
    )).scalars().all()
    assert len(rows) == 1
