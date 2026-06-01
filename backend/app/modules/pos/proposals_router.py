"""HTTP router for Slesh shop match proposals.

Endpoints:
    GET    /api/v1/pos/shop-match-proposals?event_id=...
    GET    /api/v1/pos/shop-match-proposals/count?event_id=...
    POST   /api/v1/pos/shop-match-proposals/{id}/accept
    POST   /api/v1/pos/shop-match-proposals/{id}/reject
    POST   /api/v1/pos/shop-match-proposals/{id}/skip

See docs/e2e-validation-design.md (S4 — Name-matching UX).
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.bars.models import Bar
from app.modules.pos.models import SleshShopMatchProposal
from app.modules.pos.proposals_schemas import (
    AcceptProposalRequest,
    BarSummary,
    ProposalResponse,
)
from app.modules.pos.proposals_service import (
    AcceptRequiresBarError,
    BarNotFoundError,
    ProposalAlreadyDecidedError,
    ProposalNotFoundError,
    ShopMatchProposalsService,
)


router = APIRouter()


# ─── Local tenant_id helper (same pattern as pos/router.py) ─────────────────
async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return current_user.tenant_id


# ─── Response model for the count endpoint ──────────────────────────────────
class PendingCountResponse(BaseModel):
    count: int


# ─── Helper: hydrate ProposalResponse with suggested_bar ────────────────────
async def _to_response(
    db: AsyncSession, proposal: SleshShopMatchProposal,
) -> ProposalResponse:
    """Build the response, fetching the suggested bar inline.

    We don\'t use selectinload at the service layer because most callers
    don\'t need the bar nested — only the response builder does.
    """
    suggested_bar = None
    if proposal.suggested_bar_id is not None:
        bar = await db.get(Bar, proposal.suggested_bar_id)
        if bar is not None:
            suggested_bar = BarSummary.model_validate(bar)
    return ProposalResponse(
        id=proposal.id,
        tenant_id=proposal.tenant_id,
        event_id=proposal.event_id,
        slesh_shop_id=proposal.slesh_shop_id,
        slesh_shop_name=proposal.slesh_shop_name,
        suggested_bar=suggested_bar,
        similarity_score=proposal.similarity_score,
        status=proposal.status,
        decided_at=proposal.decided_at,
        decided_by_user_id=proposal.decided_by_user_id,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


# ─── GET list pending ───────────────────────────────────────────────────────
@router.get(
    "/shop-match-proposals",
    response_model=list[ProposalResponse],
)
async def list_pending(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    event_id: Annotated[UUID, Query(description="Filter by event")],
) -> list[ProposalResponse]:
    """List PENDING shop-match proposals for an event.

    Sorted by similarity descending so the most confident suggestions
    appear first. Used by the approval UI list.
    """
    service = ShopMatchProposalsService(db)
    proposals = await service.list_pending(tenant_id, event_id)
    return [await _to_response(db, p) for p in proposals]


# ─── GET pending count (banner badge) ───────────────────────────────────────
@router.get(
    "/shop-match-proposals/count",
    response_model=PendingCountResponse,
)
async def count_pending(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    event_id: Annotated[UUID, Query(description="Count pending for this event")],
) -> PendingCountResponse:
    """Return pending proposal count — used by the dashboard banner."""
    service = ShopMatchProposalsService(db)
    n = await service.count_pending(tenant_id, event_id)
    return PendingCountResponse(count=n)


# ─── POST accept ────────────────────────────────────────────────────────────
@router.post(
    "/shop-match-proposals/{proposal_id}/accept",
    response_model=ProposalResponse,
)
async def accept_proposal(
    proposal_id: UUID,
    body: AcceptProposalRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ProposalResponse:
    """Accept a proposal: link the Slesh shop ID to a bar.

    If `bar_id` is supplied in the body, link to THAT bar (overriding
    the AI suggestion). Otherwise link to the suggested bar (must be
    non-null, else 400).

    Idempotent: accepting an already-accepted proposal returns it
    unchanged.
    """
    service = ShopMatchProposalsService(db)
    try:
        proposal = await service.accept(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            user_id=current_user.id,
            override_bar_id=body.bar_id,
        )
    except ProposalNotFoundError:
        raise HTTPException(404, "Proposal not found")
    except ProposalAlreadyDecidedError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Proposal already {e.current_status.value}; cannot transition",
        )
    except AcceptRequiresBarError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No suggested bar on this proposal — provide `bar_id` "
            "in the request body to specify the target bar",
        )
    except BarNotFoundError:
        raise HTTPException(404, "Target bar not found in this tenant")

    return await _to_response(db, proposal)


# ─── POST reject ────────────────────────────────────────────────────────────
@router.post(
    "/shop-match-proposals/{proposal_id}/reject",
    response_model=ProposalResponse,
)
async def reject_proposal(
    proposal_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ProposalResponse:
    """Reject a proposal. The shop will re-surface on the next sync."""
    service = ShopMatchProposalsService(db)
    try:
        proposal = await service.reject(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            user_id=current_user.id,
        )
    except ProposalNotFoundError:
        raise HTTPException(404, "Proposal not found")
    except ProposalAlreadyDecidedError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Proposal already {e.current_status.value}; cannot transition",
        )
    return await _to_response(db, proposal)


# ─── POST skip ──────────────────────────────────────────────────────────────
@router.post(
    "/shop-match-proposals/{proposal_id}/skip",
    response_model=ProposalResponse,
)
async def skip_proposal(
    proposal_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ProposalResponse:
    """Skip a proposal — defer decision."""
    service = ShopMatchProposalsService(db)
    try:
        proposal = await service.skip(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            user_id=current_user.id,
        )
    except ProposalNotFoundError:
        raise HTTPException(404, "Proposal not found")
    except ProposalAlreadyDecidedError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Proposal already {e.current_status.value}; cannot transition",
        )
    return await _to_response(db, proposal)
