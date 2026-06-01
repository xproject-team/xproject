"""Service layer for Slesh shop match proposals.

Owns:
  - Fuzzy matching of Slesh shop names against unlinked bars.
  - Proposal lifecycle (pending -> accepted | rejected | skipped).
  - Commit-on-accept: setting bar.slesh_negozio_id when owner accepts.

Designed to be called from:
  - sync_service.sync_shops (creates proposals on every sync)
  - pos.proposals_router    (lists pending + processes decisions)

See docs/e2e-validation-design.md (S4 — Name-matching UX).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.bars.models import Bar
from app.modules.pos.models import SleshShopMatchProposal, ShopMatchStatus

if TYPE_CHECKING:
    from app.modules.pos.schemas import Shop as SleshShop


# ─── Domain exceptions ────────────────────────────────────────────────────────
# Mapped by the router to 4xx HTTPException.

class ProposalNotFoundError(Exception):
    """Proposal not found in this tenant."""
    pass


class ProposalAlreadyDecidedError(Exception):
    """Cannot transition a proposal that is no longer pending."""
    def __init__(self, current_status: ShopMatchStatus):
        self.current_status = current_status


class AcceptRequiresBarError(Exception):
    """Accept called without an explicit bar_id AND no suggested_bar_id."""
    pass


class BarNotFoundError(Exception):
    """The bar_id provided on accept does not exist in this tenant."""
    pass


# ─── Internal helper: fuzzy matching ──────────────────────────────────────────

def _best_fuzzy_match(
    slesh_name: str,
    candidates: list[Bar],
) -> tuple[UUID | None, Decimal]:
    """Return (bar_id, similarity) for the best fuzzy match.

    Uses rapidfuzz.fuzz.token_set_ratio which handles word order,
    punctuation, and casing. Returns 0-1 normalized similarity
    (rapidfuzz returns 0-100; we /100 for storage).

    Returns (None, 0.000) when candidates is empty.
    """
    if not candidates:
        return None, Decimal("0.000")

    # Normalize: strip + collapse internal whitespace + lowercase.
    # The 2025 Slesh export had trailing spaces on bar names — naive
    # matching loses 5-15 points to that noise. token_set_ratio is
    # already case-insensitive but explicit .lower() removes any
    # asymmetry.
    def _norm(s: str) -> str:
        return " ".join(s.lower().split())

    target = _norm(slesh_name)
    best_id: UUID | None = None
    best_score = 0.0
    for bar in candidates:
        score = fuzz.token_set_ratio(target, _norm(bar.name))
        if score > best_score:
            best_score = score
            best_id = bar.id

    return best_id, (Decimal(str(round(best_score / 100.0, 3))))


# ─── Service ──────────────────────────────────────────────────────────────────

class ShopMatchProposalsService:
    """Manages the lifecycle of Slesh-shop-to-bar match proposals."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Creation (called by sync_shops) ─────────────────────────────────
    async def propose_for_shops(
        self,
        tenant_id: UUID,
        event_id: UUID,
        unmatched_shops: list["SleshShop"],
    ) -> list[SleshShopMatchProposal]:
        """For each Slesh shop with no matching bar.slesh_negozio_id,
        compute a fuzzy match against UNLINKED bars in this event and
        create a pending proposal.

        Idempotent: re-running the sync with the same shops will NOT
        create duplicate proposals (unique constraint on
        tenant_id, event_id, slesh_shop_id).

        Returns the list of NEW proposals created in this call (skipped
        duplicates omitted).
        """
        if not unmatched_shops:
            return []

        # Load candidate bars: unlinked bars in this event.
        # (Bars with slesh_negozio_id already set are matched elsewhere
        # and should NOT be suggested.)
        stmt = (
            select(Bar)
            .where(Bar.tenant_id == tenant_id)
            .where(Bar.event_id == event_id)
            .where(Bar.slesh_negozio_id.is_(None))
            .where(Bar.is_active.is_(True))
        )
        candidates = (await self.db.execute(stmt)).scalars().all()

        new_proposals: list[SleshShopMatchProposal] = []
        for shop in unmatched_shops:
            best_bar_id, similarity = _best_fuzzy_match(shop.name, candidates)
            proposal = SleshShopMatchProposal(
                tenant_id=tenant_id,
                event_id=event_id,
                slesh_shop_id=shop.id,
                slesh_shop_name=shop.name,
                suggested_bar_id=best_bar_id,
                similarity_score=similarity,
                status=ShopMatchStatus.PENDING,
            )
            # Use a SAVEPOINT (nested transaction) per insert.
            # If the unique constraint fires (duplicate proposal for
            # the same Slesh shop on a re-sync), only THIS savepoint
            # rolls back — previously created proposals + other tx
            # state remain intact. Without this, a single duplicate
            # would discard the whole batch (and in tests, blow away
            # the outer SAVEPOINT used by db_session fixture).
            try:
                async with self.db.begin_nested():
                    self.db.add(proposal)
                    await self.db.flush()
                new_proposals.append(proposal)
            except IntegrityError:
                # Already exists — savepoint auto-rolled. Continue.
                pass

        return new_proposals

    # ── Listing ─────────────────────────────────────────────────────────
    async def list_pending(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> list[SleshShopMatchProposal]:
        """Return all pending proposals for an event (approval UI input)."""
        stmt = (
            select(SleshShopMatchProposal)
            .where(SleshShopMatchProposal.tenant_id == tenant_id)
            .where(SleshShopMatchProposal.event_id == event_id)
            .where(SleshShopMatchProposal.status == ShopMatchStatus.PENDING)
            .order_by(SleshShopMatchProposal.similarity_score.desc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def count_pending(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> int:
        """Count pending proposals — for the banner badge."""
        from sqlalchemy import func
        stmt = (
            select(func.count(SleshShopMatchProposal.id))
            .where(SleshShopMatchProposal.tenant_id == tenant_id)
            .where(SleshShopMatchProposal.event_id == event_id)
            .where(SleshShopMatchProposal.status == ShopMatchStatus.PENDING)
        )
        return int((await self.db.execute(stmt)).scalar() or 0)

    # ── Decisions ───────────────────────────────────────────────────────
    async def accept(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        user_id: UUID,
        override_bar_id: UUID | None = None,
    ) -> SleshShopMatchProposal:
        """Accept a proposal: link the Slesh shop ID to a bar.

        If override_bar_id is provided, link to THAT bar (ignoring the
        suggestion). Otherwise link to the proposal\'s suggested_bar_id
        (must be non-null in that case — raises AcceptRequiresBarError).

        Idempotent: accepting an already-accepted proposal returns it
        unchanged. Re-deciding (e.g. accepting after rejecting) is
        REJECTED — raises ProposalAlreadyDecidedError. Owner must
        unilaterally relink via /bars/{id} PATCH in that case.
        """
        proposal = await self._get_or_raise(tenant_id, proposal_id)

        if proposal.status == ShopMatchStatus.ACCEPTED:
            return proposal  # idempotent
        if proposal.status != ShopMatchStatus.PENDING:
            raise ProposalAlreadyDecidedError(proposal.status)

        target_bar_id = override_bar_id or proposal.suggested_bar_id
        if target_bar_id is None:
            raise AcceptRequiresBarError()

        # Load + verify the target bar belongs to this tenant.
        bar = await self.db.get(Bar, target_bar_id)
        if bar is None or bar.tenant_id != tenant_id:
            raise BarNotFoundError()

        # Link: set the slesh_negozio_id on the bar.
        # Note: we do NOT overwrite bar.name from the Slesh side. The
        # owner-curated name is more meaningful than Slesh\'s string.
        # Future syncs may update names; that\'s a separate decision.
        bar.slesh_negozio_id = proposal.slesh_shop_id

        # Stamp the proposal.
        proposal.status = ShopMatchStatus.ACCEPTED
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.decided_by_user_id = user_id
        proposal.suggested_bar_id = target_bar_id   # snapshot the actual choice

        await self.db.commit()
        return proposal

    async def reject(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        user_id: UUID,
    ) -> SleshShopMatchProposal:
        """Reject a proposal. The Slesh shop will surface again on the
        next sync as a NEW proposal (we never auto-link rejected pairs).
        Owner has implicitly said \'these two are NOT the same\'.
        """
        proposal = await self._get_or_raise(tenant_id, proposal_id)
        if proposal.status == ShopMatchStatus.REJECTED:
            return proposal
        if proposal.status != ShopMatchStatus.PENDING:
            raise ProposalAlreadyDecidedError(proposal.status)

        proposal.status = ShopMatchStatus.REJECTED
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.decided_by_user_id = user_id
        await self.db.commit()
        return proposal

    async def skip(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        user_id: UUID,
    ) -> SleshShopMatchProposal:
        """Skip a proposal — defer decision. Will NOT re-surface on
        the next sync (the unique constraint blocks re-creation).
        Owner can manually un-skip by patching status back to pending,
        or just live with the proposal staying skipped forever.
        """
        proposal = await self._get_or_raise(tenant_id, proposal_id)
        if proposal.status == ShopMatchStatus.SKIPPED:
            return proposal
        if proposal.status != ShopMatchStatus.PENDING:
            raise ProposalAlreadyDecidedError(proposal.status)

        proposal.status = ShopMatchStatus.SKIPPED
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.decided_by_user_id = user_id
        await self.db.commit()
        return proposal

    # ── Internal ────────────────────────────────────────────────────────
    async def _get_or_raise(
        self,
        tenant_id: UUID,
        proposal_id: UUID,
    ) -> SleshShopMatchProposal:
        proposal = await self.db.get(SleshShopMatchProposal, proposal_id)
        if proposal is None or proposal.tenant_id != tenant_id:
            raise ProposalNotFoundError()
        return proposal
