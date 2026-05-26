"""HTTP router for the POS module.

Endpoints:
    GET /api/v1/pos/freshness      Slesh polling cursor health
                                   - last sync timestamp
                                   - status (ok / error / circuit_open)
                                   - seconds since last successful poll
                                   - is_live (was the cursor advanced in <60s?)

Used by:
    Frontend Dashboard freshness indicator (B8) — shows Omar whether the
    polling worker is keeping up or behind.
"""
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.pos.poll_state_models import SleshPollState


router = APIRouter()


# ─── Local tenant_id helper (same pattern as stock_transactions/router.py) ───
async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return current_user.tenant_id


# ─── Response schema ────────────────────────────────────────────────────────
class FreshnessResponse(BaseModel):
    """Freshness metadata for the dashboard.

    Fields are designed to be displayable as-is in the UI.
    """
    has_state:       bool
    last_run_at:     datetime | None
    last_status:     str | None       # ok | error | circuit_open
    last_error:      str | None       # short error excerpt if applicable
    seconds_since:   int | None       # how many seconds since last_run_at
    experience_id:   str | None       # which experience scope (None=brand-wide)
    last_seen_ts:    int | None       # cursor: ms-since-epoch of last poll window end
    is_live:         bool             # last_run_at within 60s AND status=ok
    is_stale:        bool             # last_run_at older than 120s
    brand_id:        str | None


# ─── GET /api/v1/pos/freshness ──────────────────────────────────────────────
@router.get(
    "/freshness",
    response_model=FreshnessResponse,
)
async def get_freshness(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> FreshnessResponse:
    """Return Slesh polling freshness for this tenant.

    The dashboard polls this every ~10 seconds to render a small badge:
    - is_live=True  -> green "Live" indicator
    - status=error  -> yellow "Sync delayed" indicator with last_error
    - is_stale=True -> red "Data behind >2min" indicator

    If no SleshPollState row exists yet (poller has never run for this
    tenant), returns has_state=False so the UI can show a "not started"
    state instead of crashing.
    """
    stmt = (
        select(SleshPollState)
        .where(SleshPollState.tenant_id == tenant_id)
        .where(SleshPollState.brand_id == settings.slesh_brand_id)
        .order_by(SleshPollState.last_run_at.desc().nullslast())
        .limit(1)
    )
    res = await db.execute(stmt)
    state = res.scalar_one_or_none()

    if state is None or state.last_run_at is None:
        return FreshnessResponse(
            has_state=state is not None,
            last_run_at=None,
            last_status=None,
            last_error=None,
            seconds_since=None,
            is_live=False,
            is_stale=False,
            brand_id=settings.slesh_brand_id or None,
            experience_id=state.experience_id if state else None,
            last_seen_ts=state.last_seen_ts if state else None,
        )

    now = datetime.now(tz=timezone.utc)
    seconds_since = int((now - state.last_run_at).total_seconds())
    is_live  = state.last_status == "ok"  and seconds_since < 60
    is_stale = seconds_since > 120

    return FreshnessResponse(
        has_state=True,
        last_run_at=state.last_run_at,
        last_status=state.last_status,
        last_error=state.last_error[:120] if state.last_error else None,
        seconds_since=seconds_since,
        is_live=is_live,
        is_stale=is_stale,
        brand_id=state.brand_id,
        experience_id=state.experience_id,
        last_seen_ts=state.last_seen_ts,
    )



# ─────────────────────────────────────────────────────────────────────
# GET /api/v1/pos/wristband-activity
# ─────────────────────────────────────────────────────────────────────
class WristbandActivityRow(BaseModel):
    transaction_id:  str
    created_at:      datetime
    bar_id:          str
    bar_name:        str
    product_id:      str
    product_name:    str
    qty:             float
    price_cents:     int | None


class WristbandActivityResponse(BaseModel):
    rows:  list[WristbandActivityRow]
    total: int


@router.get(
    '/wristband-activity',
    response_model=WristbandActivityResponse,
)
async def get_wristband_activity(
    db:        Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    event_id:  UUID | None = None,
    limit:     int = 50,
) -> WristbandActivityResponse:
    from sqlalchemy.orm import selectinload
    from app.modules.bars.models     import Bar
    from app.modules.products.models import Product
    from app.modules.stock_transactions.models import (
        PaymentType,
        StockTransaction,
        TransactionSource,
    )

    capped_limit = max(1, min(200, limit))

    stmt = (
        select(StockTransaction)
        .where(StockTransaction.tenant_id    == tenant_id)
        .where(StockTransaction.source       == TransactionSource.SLESH_POS)
        .where(StockTransaction.payment_type == PaymentType.TOKEN)
        .where(StockTransaction.parent_transaction_id.is_(None))
        .order_by(StockTransaction.created_at.desc())
        .limit(capped_limit)
    )
    if event_id is not None:
        stmt = stmt.where(StockTransaction.event_id == event_id)

    res = await db.execute(stmt)
    txs = res.scalars().all()

    if not txs:
        return WristbandActivityResponse(rows=[], total=0)

    bar_ids     = {tx.bar_id for tx in txs}
    product_ids = {tx.product_id for tx in txs}
    bars_map = {
        b.id: b for b in (
            await db.execute(select(Bar).where(Bar.id.in_(bar_ids)))
        ).scalars().all()
    }
    prods_map = {
        p.id: p for p in (
            await db.execute(select(Product).where(Product.id.in_(product_ids)))
        ).scalars().all()
    }

    rows: list[WristbandActivityRow] = [
        WristbandActivityRow(
            transaction_id = str(tx.id),
            created_at     = tx.created_at,
            bar_id         = str(tx.bar_id),
            bar_name       = bars_map[tx.bar_id].name if tx.bar_id in bars_map else '(unknown bar)',
            product_id     = str(tx.product_id),
            product_name   = prods_map[tx.product_id].name if tx.product_id in prods_map else '(unknown product)',
            qty            = float(tx.qty),
            price_cents    = tx.price_cents,
        )
        for tx in txs
    ]
    return WristbandActivityResponse(rows=rows, total=len(rows))
