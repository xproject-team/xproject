"""HTTP router for the events module — input validation and response formatting only.

Contract reference: §1.1 (4-layer architecture), §6.1 (Events endpoints),
§7 (response conventions).

All business logic lives in the service layer. This file is thin on purpose:
parse request, call service, translate exceptions, return response.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timezone
from pydantic import BaseModel
from app.core.database import get_db
from app.modules.auth.models import User, UserRole
from app.modules.auth.router import get_current_user
from app.modules.auth.permissions import get_active_role
from app.modules.events.schemas import (
    EventCreate,
    EventResponse,
    EventUpdate,
    FullEventCreate,
    FullEventCreateResponse,
)
from app.modules.events.reconciliation_schemas import ReconciliationReport
from app.modules.events.category_totals_schemas import (
    EventBarCategoryTotalsResponse,
)
from app.modules.events.category_totals_service import (
    BarCategoryTotalsService,
)
from app.modules.event_storage.bar_supplier_stock_service import (
    aggregate_bar_stock_pct,
    compute_bar_supplier_stock,
    fire_depletion_alerts,
)
from app.modules.event_storage.bar_supplier_stock_schemas import (
    BarAggregatedStock,
    BarSupplierStockItem,
    BarSupplierStockResponse,
)
from app.modules.events.event_kpi_schemas import EventKpiSummary
from app.modules.events.event_kpi_service import EventKpiSummaryService
from app.modules.events.menu_performance_schemas import EventMenuPerformance
from app.modules.events.menu_performance_service import MenuPerformanceService
from app.modules.events.reconciliation_service import compute_report
from app.modules.events.service import (
    EventNotFoundError,
    EventService,
    FullEventValidationError,
    EventNotDraftError,
    LiveEventConflictError,
    StaleVersionError,
    VenueNotFoundError,
)
from app.modules.events.state_machine import (
    FieldLockedError,
    InvalidTransitionError,
)


# ─── Tenant resolver ──────────────────────────────────────────────────────────
# TODO(auth): once Clerk is wired, replace with Clerk-authenticated user lookup.

async def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    """Return the authenticated user\'s tenant_id (from JWT claims)."""
    return current_user.tenant_id


# ─── Exception → HTTP translation ─────────────────────────────────────────────
# Single place where domain exceptions become HTTP responses.
# Keeps the endpoint functions clean and avoids scattered try/except blocks.

def _raise_http(exc: Exception) -> None:
    """Translate a known domain exception into an HTTPException.

    Contract §7.3 (error envelope): every error payload has at minimum
    error + message; some errors include extra context fields.
    """
    if isinstance(exc, EventNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(exc)},
        )
    if isinstance(exc, VenueNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "venue_not_found", "message": str(exc)},
        )
    if isinstance(exc, StaleVersionError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "stale_version",
                "message": str(exc),
                "current_version": exc.current_version,
            },
        )
    if isinstance(exc, LiveEventConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "event_already_live",
                "message": str(exc),
                "conflicting_event": {
                    "id": str(exc.conflicting_event.id),
                    "name": exc.conflicting_event.name,
                },
            },
        )
    if isinstance(exc, InvalidTransitionError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "invalid_transition",
                "message": str(exc),
                "from_status": exc.from_status.value,
                "to_status": exc.to_status.value,
            },
        )
    if isinstance(exc, FieldLockedError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "field_locked",
                "message": str(exc),
                "field": exc.field,
                "status": exc.status.value,
            },
        )
    raise exc  # unexpected — let FastAPI\'s default 500 handler deal with it


# ─── Router ───────────────────────────────────────────────────────────────────

router = APIRouter()


# ─── Reads ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[EventResponse])
async def list_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> list[EventResponse]:
    """List all events for the current tenant, newest first."""
    service = EventService(db)
    events = await service.list_events(tenant_id)
    responses = []
    for event in events:
        response_dict = await service.build_response_dict(event)
        responses.append(EventResponse.model_validate(response_dict))
    return responses


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventResponse:
    """Fetch a single event by ID. 404 if not found or wrong tenant."""
    service = EventService(db)
    try:
        event = await service.get_event(tenant_id, event_id)
    except EventNotFoundError as e:
        _raise_http(e)
    response_dict = await service.build_response_dict(event)
    return EventResponse.model_validate(response_dict)


# ─── Create ───────────────────────────────────────────────────────────────────

@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventResponse:
    """Create a new event (always status=draft). 404 if venue invalid."""
    service = EventService(db)
    try:
        event = await service.create_event(tenant_id, payload)
    except VenueNotFoundError as e:
        _raise_http(e)
    response_dict = await service.build_response_dict(event)
    return EventResponse.model_validate(response_dict)


# ─── Update ───────────────────────────────────────────────────────────────────

@router.post(
    "/full",
    response_model=FullEventCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_full_event(
    payload: FullEventCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> FullEventCreateResponse:
    """Create event + bars + products + menu + allocations in ONE transaction.

    All-or-nothing (Phase D wizard backend). Error responses:
    - 404 venue_not_found
    - 422 full_event_validation_failed (per-item report in detail.items)
    """
    service = EventService(db)
    try:
        result = await service.create_full(tenant_id, payload)
    except VenueNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "venue_not_found", "message": str(e)},
        )
    except FullEventValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "full_event_validation_failed",
                "message": str(e),
                "items": [it.model_dump() for it in e.errors],
            },
        )
    event_dict = await service.build_response_dict(result["event"])
    return FullEventCreateResponse(
        event=EventResponse(**event_dict),
        bars_created=result["bars_created"],
        products_created=result["products_created"],
        products_reused=result["products_reused"],
        menu_items_created=result["menu_items_created"],
        allocations_created=result["allocations_created"],
    )


@router.put(
    "/{event_id}/full",
    response_model=FullEventCreateResponse,
)
async def update_full_event(
    event_id: UUID,
    payload: FullEventCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> FullEventCreateResponse:
    """Restructure a DRAFT event from the wizard (replace semantics).

    Error responses:
    - 404 event_not_found / venue_not_found
    - 422 event_not_draft (LIVE/completed events cannot be restructured)
    - 422 full_event_validation_failed (per-item report in detail.items)
    """
    service = EventService(db)
    try:
        result = await service.update_full(tenant_id, event_id, payload)
    except EventNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    except EventNotDraftError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "event_not_draft", "message": str(e)},
        )
    except VenueNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "venue_not_found", "message": str(e)},
        )
    except FullEventValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "full_event_validation_failed",
                "message": str(e),
                "items": [it.model_dump() for it in e.errors],
            },
        )
    event_dict = await service.build_response_dict(result["event"])
    return FullEventCreateResponse(
        event=EventResponse(**event_dict),
        bars_created=result["bars_created"],
        products_created=result["products_created"],
        products_reused=result["products_reused"],
        menu_items_created=result["menu_items_created"],
        allocations_created=result["allocations_created"],
    )


@router.patch("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: UUID,
    payload: EventUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventResponse:
    """Update an event\'s editable fields.

    Requires `version` in the body (optimistic locking, contract §4).
    Returns 409 if version is stale OR if any field is locked in the
    current status (e.g. changing venue on a Live event).
    """
    service = EventService(db)
    try:
        event = await service.update_event(tenant_id, event_id, payload)
    except (
        EventNotFoundError, VenueNotFoundError,
        StaleVersionError, FieldLockedError,
    ) as e:
        _raise_http(e)
    response_dict = await service.build_response_dict(event)
    return EventResponse.model_validate(response_dict)


# ─── Delete ───────────────────────────────────────────────────────────────────

@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> Response:
    """Delete a DRAFT event (children CASCADE). 409 for non-Draft statuses."""
    service = EventService(db)
    try:
        await service.delete_event(tenant_id, event_id)
    except (EventNotFoundError, InvalidTransitionError) as e:
        _raise_http(e)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── Status transitions ───────────────────────────────────────────────────────

@router.post("/{event_id}/activate", response_model=EventResponse)
async def activate_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventResponse:
    """Transition DRAFT → ACTIVE. Idempotent: calling on Active is a no-op."""
    service = EventService(db)
    try:
        event = await service.activate_event(tenant_id, event_id)
    except (EventNotFoundError, InvalidTransitionError) as e:
        _raise_http(e)
    response_dict = await service.build_response_dict(event)
    return EventResponse.model_validate(response_dict)


@router.post("/{event_id}/start", response_model=EventResponse)
async def start_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventResponse:
    """Transition ACTIVE → LIVE.

    Enforces one-live-per-tenant invariant with auto-end-if-stale logic
    (contract Q1 hybrid). Returns 409 with conflicting_event info if
    another event is genuinely live.
    """
    service = EventService(db)
    try:
        event = await service.start_event(tenant_id, event_id)
    except (
        EventNotFoundError, InvalidTransitionError, LiveEventConflictError,
    ) as e:
        _raise_http(e)
    response_dict = await service.build_response_dict(event)
    return EventResponse.model_validate(response_dict)


@router.post("/{event_id}/end", response_model=EventResponse)
async def end_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventResponse:
    """Transition LIVE → COMPLETED. Idempotent."""
    service = EventService(db)
    try:
        event = await service.end_event(tenant_id, event_id)
    except (EventNotFoundError, InvalidTransitionError) as e:
        _raise_http(e)
    response_dict = await service.build_response_dict(event)
    return EventResponse.model_validate(response_dict)



# ─── Weather (B.10) ───────────────────────────────────────────────────────────
class EventWeatherResponse(BaseModel):
    """Slim shape for the dashboard weather pill + post-event reports.

    `snapshot` is the raw Open-Meteo response (JSONB column dumped as-is)
    when present, or None if the weather sync has not run for this event.
    The frontend reads `snapshot.current` for the pill and `snapshot.hourly`
    for the upcoming-hours strip.
    """
    event_id:           UUID
    weather_fetched_at: datetime | None = None
    snapshot:           dict | None      = None
    is_stale:           bool             = False    # >2h since fetch


@router.get("/{event_id}/weather", response_model=EventWeatherResponse)
async def get_event_weather(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventWeatherResponse:
    """Return the most recent weather snapshot persisted on the event row.

    Behavior:
      - 404 if the event does not exist for this tenant.
      - 200 with snapshot=None if the event exists but weather was never synced.
      - 200 with the full snapshot otherwise.
    """
    service = EventService(db)
    try:
        event = await service.get_event(tenant_id, event_id)
    except EventNotFoundError as e:
        _raise_http(e)

    is_stale = False
    if event.weather_fetched_at is not None:
        age = datetime.now(tz=timezone.utc) - event.weather_fetched_at
        is_stale = age.total_seconds() > 7200    # 2 hours

    return EventWeatherResponse(
        event_id           = event.id,
        weather_fetched_at = event.weather_fetched_at,
        snapshot           = event.weather_snapshot,
        is_stale           = is_stale,
    )


# ─── Reconciliation report ───────────────────────────────────────────────────
# Phase 6.11: per-(bar, product) reconciliation grid + per-product event-level
# delivery-gap detection. Owner-only — Manager-scoped variant ships later if
# Omar requests it.
#
# Sundance-safety

@router.get(
    "/{event_id}/bar-category-totals",
    response_model=EventBarCategoryTotalsResponse,
)
async def get_event_bar_category_totals(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventBarCategoryTotalsResponse:
    """Per-bar, per-category sales totals for the dashboard.

    Returns each bar in the event with:
      - 4+1 display buckets (beer / cocktails / premium_cocktails /
        wine / food) with units + revenue rolled up
      - Top 5 drinks by units sold, each labeled with its GRANULAR
        category (e.g. "Cocktail signature" → premium_cocktail)
      - total_units and total_revenue_eur across all transactions

    Categorization is hybrid: Product.category enum when set,
    name-derived fallback via _classify_category() otherwise.
    """
    service = BarCategoryTotalsService(db)
    result = await service.get_for_event(tenant_id=tenant_id, event_id=event_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    return result


@router.get(
    "/{event_id}/bar-supplier-stock",
    response_model=BarSupplierStockResponse,
)
async def get_event_bar_supplier_stock(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    bar_id: UUID | None = None,
) -> BarSupplierStockResponse:
    """Per-(bar, supplier_product) ml-depletion stock with status.

    Implements the worst-case high-recall depletion math for Sundance 14:
    every transaction in a Slesh-category C decrements ALL supplier_products
    mapped to C via event_category_ingredients (NULL bar_id = any bar; set
    bar_id = restricted to that bar — e.g. GIN No 3 sponsor at NO.3 BAR).

    Returns:
      - items: per-(bar, supplier_product) rows with dispatched_ml,
        consumed_ml, remaining_ml, remaining_pct, status, thresholds
      - by_bar: Σ-aggregated per-bar stock % for the bar-card indicator

    Optional bar_id query param filters to a single bar (used by the
    BarDetailOverlay STOCK section).
    """
    rows = await compute_bar_supplier_stock(
        session=db,
        tenant_id=tenant_id,
        event_id=event_id,
        bar_id=bar_id,
    )
    # Side-effect: fire/update/auto-resolve depletion alerts on status flips.
    # Idempotent — dedup on (bar, supplier_product) via context_json.
    # Only do this when the request is unbounded (covers all bars), so a
    # filtered single-bar call doesn't accidentally bypass cross-bar alerts.
    if bar_id is None:
        await fire_depletion_alerts(
            session=db,
            tenant_id=tenant_id,
            event_id=event_id,
            rows=rows,
        )
        # Persist any alerts created / updated / auto-resolved. The session
        # dependency does NOT auto-commit; without this, alerts would roll
        # back when the request returns.
        await db.commit()
    items = [
        BarSupplierStockItem(
            bar_id=r.bar_id,
            bar_name=r.bar_name,
            supplier_product_id=r.supplier_product_id,
            item_name=r.item_name,
            dispatched_units=r.dispatched_units,
            dispatched_ml=r.dispatched_ml,
            consumed_ml=r.consumed_ml,
            remaining_ml=r.remaining_ml,
            remaining_pct=r.remaining_pct,
            status=r.status,  # type: ignore[arg-type]
            threshold_pct_warn=r.threshold_pct_warn,
            threshold_pct_empty=r.threshold_pct_empty,
            accurate=r.accurate,
        )
        for r in rows
    ]
    by_bar_map = await aggregate_bar_stock_pct(rows)
    by_bar = [
        BarAggregatedStock(
            bar_id=b_id,
            bar_name=slot["bar_name"],
            dispatched_ml=slot["dispatched_ml"],
            remaining_ml=slot["remaining_ml"],
            pct=slot["pct"],
            status=slot["status"],  # type: ignore[arg-type]
        )
        for b_id, slot in by_bar_map.items()
    ]
    by_bar.sort(key=lambda b: b.bar_name)
    return BarSupplierStockResponse(
        event_id=event_id,
        items=items,
        by_bar=by_bar,
    )
# Why this query is safe to run live: single SQL roundtrip (no inter-row race during live event),
# event-window bounded, voided scans excluded, tenant-scoped at every CTE,
# Decimal precision preserved across the wire.


@router.get(
    "/{event_id}/kpi-summary",
    response_model=EventKpiSummary,
)
async def get_event_kpi_summary(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventKpiSummary:
    """Event-level KPI rollup for the dashboard top strip.

    Returns:
      - total_revenue_eur: Omar's NET take = drinks (100%) + food (x share)
      - drinks: units + revenue, broken into 4 families
        (cocktails / beer / wine / soft) + "other"
      - food: units + GROSS revenue by FoodType, the event's share %, and
        Omar's NET cut

    404 if the event is not found for this tenant. An existing event with
    no revenue rows yet returns a zeroed summary (200).
    """
    service = EventKpiSummaryService(db)
    result = await service.get_for_event(tenant_id=tenant_id, event_id=event_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    return result


@router.get(
    "/{event_id}/menu-performance",
    response_model=EventMenuPerformance,
)
async def get_event_menu_performance(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> EventMenuPerformance:
    """Full-menu performance for the dashboard breakdown panel.

    Every drink and food menu item with units sold (zero-sold included):
      - drinks grouped by family (cocktails/beer/wine/soft/other),
        totalled per product across all bars
      - food grouped by truck (bar), each truck listing its items

    Deposits/supply/ingredient lines excluded. 404 if the event is not
    found for this tenant.
    """
    service = MenuPerformanceService(db)
    result = await service.get_for_event(tenant_id=tenant_id, event_id=event_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    return result

@router.get(
    "/{event_id}/reconciliation-report",
    response_model=ReconciliationReport,
    summary="Reconciliation report (Owner only)",
)
async def get_reconciliation_report(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ReconciliationReport:
    """Return the reconciliation grid for one event.

    Compares per-(bar, product) DISPATCH and CONSUMED scan totals against
    per-product warehouse_allocations.dispatched_qty. Surfaces three gap
    severities (MINOR/MODERATE/MAJOR) and the catastrophic "stock
    dispatched but zero arrivals" pattern.

    POS data is not yet wired (Slesh sandbox pending) — summary.totals.
    missing_pos_data is True for now; will flip when the integration lands.
    """
    if get_active_role(current_user) != UserRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Owners can view the reconciliation report.",
        )

    try:
        return await compute_report(
            db,
            tenant_id=tenant_id,
            event_id=event_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        _raise_http(exc)
        raise   # _raise_http always raises; keeps mypy happy

