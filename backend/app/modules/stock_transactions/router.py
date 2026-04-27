"""HTTP router for stock_transactions.

Endpoints:
    GET  /stock-transactions/by-event/{event_id}              ledger history
    POST /stock-transactions/sale                              POS-driven sale (cascade)
    POST /stock-transactions/adjustment                        manual adjustment (single row)
    GET  /stock-transactions/reconciliation/by-event/{id}      reconciliation report

Idempotency behavior on /sale:
- First POST with (tenant, source=slesh_pos, key) -> 201, writes ledger rows
- Duplicate POST with same key -> 200 (NOT 201), returns existing rows,
  response body has idempotency_replay=true. Critical for POS retries.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.auth.access_guards import assert_bar_access, resolve_bar_filter
from app.modules.stock_transactions.models import TransactionSource
from app.modules.stock_transactions.schemas import (
    ManualAdjustmentRequest,
    ReconciliationReport,
    SaleIngestRequest,
    SaleIngestResponse,
    StockTransactionResponse,
)
from app.modules.stock_transactions.service import (
    BarNotFoundError,
    BarNotInEventError,
    EventNotFoundError,
    MissingIdempotencyKeyError,
    NotADrinkError,
    ProductArchivedError,
    ProductNotFoundError,
    StockTransactionService,
)


async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return current_user.tenant_id


router = APIRouter()


# ─── Read: ledger history ─────────────────────────────────────────────────────

@router.get(
    "/by-event/{event_id}",
    response_model=list[StockTransactionResponse],
)
async def list_transactions_for_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    bar_id: Annotated[UUID | None, Query(description="Filter by bar")] = None,
    source: Annotated[
        TransactionSource | None,
        Query(description="Filter by source"),
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=500, description="Max rows (default/max 500)"),
    ] = 500,
) -> list[StockTransactionResponse]:
    """Ledger rows for an event, newest first.

    Bar-scoped per spec docs/bar-dashboard-spec.md S9: Manager/Bartender
    are auto-locked to their assignedBarId; Owner can pass any bar_id or
    None for all bars.
    """
    bar_id = resolve_bar_filter(current_user, bar_id)
    assert_bar_access(current_user, bar_id)
    service = StockTransactionService(db)
    try:
        rows = await service.list_for_event(
            current_user.tenant_id, event_id,
            bar_id=bar_id, source=source, limit=limit,
        )
    except EventNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    return [StockTransactionResponse.model_validate(r) for r in rows]


# ─── Write: POS sale ingestion (cascade) ──────────────────────────────────────

@router.post(
    "/sale",
    response_model=SaleIngestResponse,
)
async def ingest_sale(
    payload: SaleIngestRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> SaleIngestResponse:
    """Ingest a drink sale. Full cascade writes parent + child rows
    and decrements bar_stock with clamp-at-0 policy for any insufficient
    ingredients.

    Responses:
    - 201 Created    : new rows written (normal path)
    - 200 OK         : idempotent replay hit (rows already existed)
    - 404            : event/bar/product not found
    - 422            : not_a_drink / bar_not_in_event / product_archived /
                       missing_idempotency_key
    """
    service = StockTransactionService(db)
    try:
        result = await service.ingest_sale(tenant_id, payload)
    except EventNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    except BarNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "bar_not_found", "message": str(e)},
        )
    except BarNotInEventError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "bar_not_in_event", "message": str(e)},
        )
    except ProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "product_not_found", "message": str(e)},
        )
    except ProductArchivedError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "product_archived", "message": str(e)},
        )
    except NotADrinkError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "not_a_drink",
                "message": str(e),
                "actual_type": e.actual_type,
            },
        )
    except MissingIdempotencyKeyError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "missing_idempotency_key", "message": str(e)},
        )

    # Set status code based on replay flag
    response.status_code = (
        status.HTTP_200_OK
        if result.idempotency_replay
        else status.HTTP_201_CREATED
    )
    return SaleIngestResponse(
        parent=StockTransactionResponse.model_validate(result.parent),
        children=[
            StockTransactionResponse.model_validate(c) for c in result.children
        ],
        idempotency_replay=result.idempotency_replay,
    )


# ─── Write: manual adjustment ─────────────────────────────────────────────────

@router.post(
    "/adjustment",
    response_model=StockTransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_adjustment(
    payload: ManualAdjustmentRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> StockTransactionResponse:
    """Record a manual stock change (breakage, comp, reconciliation correction).

    No cascade — writes a single ledger row with the same clamp-at-0 policy
    as sales for the affected product.
    """
    service = StockTransactionService(db)
    try:
        tx = await service.record_adjustment(tenant_id, payload)
    except EventNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    except BarNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "bar_not_found", "message": str(e)},
        )
    except BarNotInEventError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "bar_not_in_event", "message": str(e)},
        )
    except ProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "product_not_found", "message": str(e)},
        )
    except ProductArchivedError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "product_archived", "message": str(e)},
        )
    return StockTransactionResponse.model_validate(tx)


# ─── Read: reconciliation report ──────────────────────────────────────────────

@router.get(
    "/reconciliation/by-event/{event_id}",
    response_model=ReconciliationReport,
)
async def reconciliation_report(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> ReconciliationReport:
    """Expected vs. actual depletion report for an event.

    Computed on demand (no caching, no scheduling). Typical compute is
    milliseconds for Sundance-scale events.
    """
    service = StockTransactionService(db)
    try:
        return await service.get_reconciliation_report(tenant_id, event_id)
    except EventNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )

@router.get(
    "/burn-rate/by-event/{event_id}",
)
async def burn_rate_by_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    bar_id: UUID | None = None,
) -> list[dict]:
    """Per-product burn rate for a live event, optionally filtered by bar.

    Adaptive window: 30/60/120min, falls back to full event if quiet.
    Returns: list of { product_id, bar_id, window_minutes, actual_consumed,
    burn_rate_per_hour, current_qty, time_to_depletion_min }.
    """
    bar_id = resolve_bar_filter(current_user, bar_id)
    assert_bar_access(current_user, bar_id)
    service = StockTransactionService(db)
    return await service.compute_burn_rates(current_user.tenant_id, event_id, bar_id)
