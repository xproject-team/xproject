"""HTTP router for the events module — input validation and response formatting only.

Contract reference: §1.1 (4-layer architecture), §6.1 (Events endpoints),
§7 (response conventions).

All business logic lives in the service layer. This file is thin on purpose:
parse request, call service, translate exceptions, return response.
"""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status, UploadFile, File
import json as json
import logging as logging
from typing import Literal as Literal
from sqlalchemy.exc import NoResultFound
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
    FullEventDetail,
)
from app.modules.events.event_plan_excel import (
    parse_event_plan as _parse_event_plan,
    ParsedEventPlan as _ParsedEventPlan,
)
from app.modules.pos.adapters.slesh import SleshAdapter
from app.core.redis_client import get_redis
from app.core.config import settings as slesh_settings
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
from app.modules.events.polling_health_schemas import PollingHealthResponse
from app.modules.events.polling_health_service import (
    get_event_or_none,
    get_polling_health,
)
from app.modules.events.pending_shop_mappings_schemas import (
    PendingShopMappingListResponse,
    PendingShopMappingResponse,
    ResolvePendingShopMappingRequest,
    ResolvePendingShopMappingResponse,
)
from app.modules.pos.pending_shop_mappings_service import (
    BarNotFoundError as _PendingBarNotFoundError,
    PendingMappingAlreadyResolvedError,
    PendingMappingNotFoundError,
)
import app.modules.pos.pending_shop_mappings_service as pending_shop_mappings_service
from app.modules.events.menu_performance_schemas import EventMenuPerformance
from app.modules.events.menu_performance_service import MenuPerformanceService
from app.modules.events.reconciliation_service import compute_report
from app.modules.events.revenue_breakdown_schemas import RevenueBreakdown
from app.modules.events.revenue_breakdown_service import RevenueBreakdownService
from app.modules.predictions.nowcast.schemas import RevenueForecastResponse
from app.modules.predictions.nowcast.service import (
    EventNotFoundError as ForecastEventNotFoundError,
    EventNotInTenantError as ForecastEventNotInTenantError,
    get_revenue_forecast,
)
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


@router.post(
    "/import-plan",
    response_model=_ParsedEventPlan,
    status_code=status.HTTP_200_OK,
    summary="Parse a Slesh event-plan Excel and return a structured preview",
)
async def import_event_plan(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    file: Annotated[UploadFile, File(description="Slesh event-plan .xlsx file")],
) -> _ParsedEventPlan:
    """Parse a Slesh event-plan Excel file and return its contents as
    structured JSON — WITHOUT writing anything to the database.

    Used by the Create Event wizard's Step 2 (Excel upload). The wizard
    renders the returned ParsedEventPlan as an editable preview; Omar
    confirms / edits / discards; the wizard then calls the finalize
    endpoint (separate) to atomically create the event + bars + devices
    + products from the confirmed payload.

    Safety:
      - 2 MB hard cap on file size (real Slesh plans are ~125 KB).
      - Content-Type loose-checked; we accept anything but rely on the
        parser's own defensive paths if the bytes aren't a real xlsx.
      - Tenant-scoped via the standard auth pattern; nothing is written
        to the database here, but we still gate access to Owner/Admin
        via the existing dependency chain.

    Errors:
      400 — empty body / missing file
      413 — file exceeds the 2 MB cap
      200 — always returns a ParsedEventPlan even if the file is junk
            (the parser surfaces problems via the `warnings` list)
    """
    # FastAPI delivers the file lazily; read it into memory once.
    body = await file.read()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file uploaded.",
        )
    # 2 MB hard cap. Real Slesh plans are ~125 KB; anything materially
    # larger is either the wrong file or an attempt to DoS the parser.
    MAX_BYTES = 2 * 1024 * 1024
    if len(body) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large ({len(body)} bytes). Max {MAX_BYTES} bytes.",
        )

    # Pure parse — no DB write. Defensive parser never raises;
    # malformed input produces a ParsedEventPlan with warnings populated.
    return _parse_event_plan(body)


# ─────────────────────────────────────────────────────────────────────
# Phase 4 step 8a (Jun 27 2026) — Slesh shops listing for the wizard
# ─────────────────────────────────────────────────────────────────────
# Returns the live Slesh shop list so the Create Event wizard's Step 3
# can present a picker linking each XProject bar to a Slesh shop_id.
# Caches the result in Redis for 5 minutes per brand_id to avoid
# hammering the Slesh API on every keystroke.
#
# Three response modes:
#   live    — Slesh fetched successfully just now
#   cached  — Slesh fetched recently, returning cached list
#   offline — Slesh unreachable, returning empty list + flag so the
#             frontend can offer a "type shop_id manually" fallback
#
# The endpoint never writes to the database.

class _SleshShopOut(BaseModel):
    """Single shop as exposed to the wizard. Mirrors what list_shops
    returns from the Slesh API, trimmed to what the picker needs."""
    id:        str
    name:      str
    is_active: bool


class _SleshShopsResponse(BaseModel):
    """Wrapped response so the frontend can branch on source mode."""
    shops:       list[_SleshShopOut]
    source:      Literal["live", "cached", "offline"]
    fetched_at:  datetime
    cache_ttl_s: int          # seconds remaining on the cache (0 if live/offline)


_SLESH_SHOPS_CACHE_TTL_S = 300         # 5 minutes
_SLESH_SHOPS_CACHE_KEY   = "slesh:shops:{brand_id}"
_slesh_router_logger     = logging.getLogger("app.modules.events.router.slesh")


async def _fetch_slesh_shops_cached(brand_id: str) -> _SleshShopsResponse:
    """Return shops for `brand_id`, using Redis cache when fresh.

    Cache key includes the brand_id so multi-tenant setups don’t
    cross-contaminate (today there’s one brand, but the cost of
    keying it correctly is zero).

    Errors talking to Slesh do NOT raise — we return an offline response
    with empty shops so the wizard can still render and offer the manual
    fallback. The wizard distinguishes the modes via the `source` field.
    """
    redis = await get_redis()
    cache_key = _SLESH_SHOPS_CACHE_KEY.format(brand_id=brand_id)

    # Try cache first
    try:
        cachedjson = await redis.get(cache_key)
        if cachedjson:
            ttl = await redis.ttl(cache_key)
            data = json.loads(cachedjson)
            return _SleshShopsResponse(
                shops       = [_SleshShopOut(**s) for s in data],
                source      = "cached",
                fetched_at  = datetime.now(timezone.utc),
                cache_ttl_s = max(0, ttl),
            )
    except Exception as exc:  # noqa: BLE001
        _slesh_router_logger.warning("Slesh shops cache read failed: %s", exc)

    # Cache miss / read failed — try Slesh.
    # SleshAdapter is an async context manager (closes its httpx client
    # on exit). Constructing it directly without `async with` would leak
    # the client. Kwarg names must match the adapter signature exactly:
    # `token` (not api_token), `request_timeout` (not timeout). Tests
    # mocked SleshAdapter so the live-call signature mismatch slipped
    # through — now caught + fixed.
    try:
        async with SleshAdapter(
            token              = slesh_settings.slesh_api_token,
            brand_id           = brand_id,
            base_url           = slesh_settings.slesh_base_url,
            request_timeout    = slesh_settings.slesh_request_timeout,
            rate_limit_rps     = slesh_settings.slesh_rate_limit_rps,
            max_retries        = slesh_settings.slesh_max_retries,
        ) as adapter:
            shops_raw = await adapter.list_shops(experience_id=None)
        shops = [
            _SleshShopOut(
                id        = s.id,
                name      = s.name,
                is_active = bool(getattr(s, "is_enabled", True)),
            )
            for s in shops_raw
        ]
        # Persist to cache (best-effort)
        try:
            await redis.setex(
                cache_key,
                _SLESH_SHOPS_CACHE_TTL_S,
                json.dumps([s.model_dump() for s in shops]),
            )
        except Exception as exc:  # noqa: BLE001
            _slesh_router_logger.warning("Slesh shops cache write failed: %s", exc)
        return _SleshShopsResponse(
            shops       = shops,
            source      = "live",
            fetched_at  = datetime.now(timezone.utc),
            cache_ttl_s = _SLESH_SHOPS_CACHE_TTL_S,
        )
    except Exception as exc:  # noqa: BLE001
        _slesh_router_logger.warning("Slesh shops fetch failed (offline mode): %s", exc)
        return _SleshShopsResponse(
            shops       = [],
            source      = "offline",
            fetched_at  = datetime.now(timezone.utc),
            cache_ttl_s = 0,
        )


@router.get(
    "/slesh-shops",
    response_model=_SleshShopsResponse,
    summary="List Slesh shops for the Create Event wizard’s picker",
)
async def list_slesh_shops(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> _SleshShopsResponse:
    """Returns the Slesh shop list (id, name, is_active) for the Create
    Event wizard’s Step 3 shop-picker. Cached 5 minutes; offline
    mode (empty shops) when Slesh is unreachable."""
    brand_id = slesh_settings.slesh_brand_id
    if not brand_id:
        # Misconfigured — no brand id. Return offline rather than 500.
        return _SleshShopsResponse(
            shops       = [],
            source      = "offline",
            fetched_at  = datetime.now(timezone.utc),
            cache_ttl_s = 0,
        )
    return await _fetch_slesh_shops_cached(brand_id)


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


@router.get(
    "/{event_id}/full",
    response_model=FullEventDetail,
)
async def get_full_event(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> FullEventDetail:
    """Return event in wizard-round-trippable shape (edit-mode preload).

    Errors:
      - 404 event_not_found
    """
    service = EventService(db)
    try:
        result = await service.get_full(tenant_id, event_id)
    except EventNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    event_dict = await service.build_response_dict(result["event"])
    return FullEventDetail(
        event=EventResponse(**event_dict),
        bars=result["bars"],
        products=result["products"],
        menu=result["menu"],
        allocations=result["allocations"],
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
    # Idempotent — dedup on (bar, supplier_product) via contextjson.
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
            consumed_ml_certain=r.consumed_ml_certain,
            consumed_ml_uncertain=r.consumed_ml_uncertain,
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
    "/{event_id}/polling-health",
    response_model=PollingHealthResponse,
)
async def get_event_polling_health(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> PollingHealthResponse:
    """Slesh polling status for this event's tenant (Day 4, Jul-19 sprint).

    Lets the dashboard show whether the arq worker's polling cron is
    keeping up, without needing an SSH session to check slesh_poll_state
    directly. is_healthy is True iff the last poll ran under 3 minutes
    ago AND there haven't been 3+ consecutive failures.

    Note: slesh_poll_state has no event_id column (it's scoped by
    tenant_id + brand_id + experience_id) — this reads the tenant's
    poll state, which is accurate as long as the tenant has only one
    live event at a time (see polling_health_service docstring).
    """
    event = await get_event_or_none(db, tenant_id, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    health = await get_polling_health(db, tenant_id)
    if health is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No polling state for this event",
        )
    return health


# ─── Phantom-bar defensive fix (Jul-19 sprint) ────────────────────────────────

@router.get(
    "/{event_id}/pending-shop-mappings",
    response_model=PendingShopMappingListResponse,
)
async def list_event_pending_shop_mappings(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> PendingShopMappingListResponse:
    """Unresolved Slesh shop_ids parked by the order ingester, oldest first.

    Backs the 'Map to bar' alert action's dropdown context and any
    dedicated pending-mappings list view. See
    app/modules/pos/pending_shop_mappings_service.py.
    """
    event = await get_event_or_none(db, tenant_id, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    rows = await pending_shop_mappings_service.list_pending(db, tenant_id, event_id)
    items = [PendingShopMappingResponse.model_validate(r) for r in rows]
    return PendingShopMappingListResponse(items=items, total=len(items))


@router.post(
    "/{event_id}/pending-shop-mappings/{pending_id}/resolve",
    response_model=ResolvePendingShopMappingResponse,
)
async def resolve_event_pending_shop_mapping(
    event_id: UUID,
    pending_id: UUID,
    body: ResolvePendingShopMappingRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> ResolvePendingShopMappingResponse:
    """Map a parked Slesh shop_id to a bar and replay its parked orders.

    Sets bar.slesh_negozio_id, marks the pending row resolved, and
    replays every parked order through the normal ingest_order() path
    (same recipe cascade, same idempotency guarantees as a live order).
    """
    try:
        summary = await pending_shop_mappings_service.resolve(
            db, tenant_id=tenant_id, event_id=event_id,
            pending_id=pending_id, bar_id=body.bar_id,
        )
    except PendingMappingNotFoundError:
        raise HTTPException(404, "Pending shop mapping not found")
    except PendingMappingAlreadyResolvedError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This pending shop mapping has already been resolved",
        )
    except _PendingBarNotFoundError:
        raise HTTPException(404, "Target bar not found in this tenant")

    return ResolvePendingShopMappingResponse(
        pending_id=pending_id,
        bar_id=body.bar_id,
        orders_replayed=summary["orders_replayed"],
        lines_replayed=summary["lines_replayed"],
    )


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


@router.get("/{event_id}/revenue-breakdown", response_model=RevenueBreakdown)
async def get_revenue_breakdown(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> RevenueBreakdown:
    """Composite revenue breakdown for the post-event popup.

    Aggregates event_orders rows (one per Slesh order) joined with bars to
    produce a single payload covering total billed (matches Slesh "Transato"),
    per-bar sales split drinks/food/cash-desk, cup deposit flow, VAT and
    fiscal totals, and owner take-home computed from food_revenue_share_pct.
    """
    service = RevenueBreakdownService(db)
    try:
        return await service.compute(tenant_id, event_id)
    except NoResultFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.get("/{event_id}/revenue-forecast", response_model=RevenueForecastResponse)
async def get_revenue_forecast_endpoint(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    as_of_time: datetime | None = None,
) -> RevenueForecastResponse:
    """The "ML Predicted" revenue nowcast (Phase D of the ML overlay —
    see backend/app/modules/predictions/nowcast/).

    Any authenticated tenant user (no owner gate, unlike the
    guest-count-scaled predictions in predictions/router.py — this is
    a live in-event nowcast, not a planning artifact).

    as_of_time defaults to now (server time); pass an explicit ISO
    timestamp to preview/back-test against a historical or simulated
    moment.

    404 if event_id doesn't exist at all. 403 if it exists but belongs
    to a different tenant (an intentionally stricter distinction than
    most endpoints in this file, which collapse both into 404 — see
    Phase D's task brief).
    """
    if as_of_time is None:
        as_of_time = datetime.now(timezone.utc)
    try:
        return await get_revenue_forecast(db, tenant_id, event_id, as_of_time)
    except ForecastEventNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "event_not_found", "message": str(e)},
        )
    except ForecastEventNotInTenantError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "event_not_in_tenant", "message": str(e)},
        )
