"""Pydantic v2 request/response schemas for Slesh shop match proposals.

See docs/e2e-validation-design.md (S4 — Name-matching UX).
"""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.pos.models import ShopMatchStatus


# ─── Response ────────────────────────────────────────────────────────────────

class BarSummary(BaseModel):
    """Minimal bar info embedded in the proposal response so the
    approval UI can render the suggested bar inline."""
    model_config = ConfigDict(from_attributes=True)

    id:   UUID
    name: str


class ProposalResponse(BaseModel):
    """Shape returned by GET /pos/shop-match-proposals and friends."""
    model_config = ConfigDict(from_attributes=True)

    id:               UUID
    tenant_id:        UUID
    event_id:         UUID
    slesh_shop_id:    str
    slesh_shop_name:  str
    suggested_bar:    BarSummary | None     # populated when suggested_bar_id is set
    similarity_score: Decimal
    status:           ShopMatchStatus
    decided_at:       datetime | None
    decided_by_user_id: UUID | None
    created_at:       datetime
    updated_at:       datetime


# ─── Decision request bodies ─────────────────────────────────────────────────

class AcceptProposalRequest(BaseModel):
    """Accept payload. If `bar_id` is provided, link the Slesh shop to
    that bar (overriding the suggestion). If omitted, link to the
    suggested_bar_id (must be non-null in that case).
    """
    bar_id: UUID | None = None


# Reject and Skip have no body — bare POSTs.
