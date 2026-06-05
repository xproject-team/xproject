"""Composite event create tests (Phase D.B5 — Create Event wizard backend).

Covers EventService.create_full:
- happy path: event + bars + products + menu + allocations, correct counts
  and persisted rows
- products reused by (name, product_type) when an active match exists
- all-or-nothing: an out-of-range index rejects the whole payload and
  persists ZERO rows (no orphan event)
- duplicate product (name, type) inside the payload rejected
- unknown venue → VenueNotFoundError
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.modules.bar_stock.models import BarStock
from app.modules.bars.models import Bar
from app.modules.event_products.models import EventProduct
from app.modules.events.schemas import (
    EventCreate,
    FullEventAllocation,
    FullEventBar,
    FullEventCreate,
    FullEventMenuItem,
    FullEventProductInput,
)
from app.modules.events.service import EventService, VenueNotFoundError
from app.modules.venues.models import Venue
from app.modules.events.service import FullEventValidationError
from app.modules.products.models import (
    Product,
    ProductCategory,
    ProductType,
    ProductUnit,
)
from tests.fixtures.alerts.factories import (
    _SUNDANCE_VENUE_ID,
    delete_tenant_cascade,
    make_product,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal


async def _make_venue(session, tenant_id) -> Venue:
    v = Venue(tenant_id=tenant_id, name=f"venue-{uuid.uuid4().hex[:8]}")
    session.add(v)
    await session.flush()
    return v


def _event_create(venue_id) -> EventCreate:
    now = datetime.now(timezone.utc)
    return EventCreate(
        name=f"full-event-{uuid.uuid4().hex[:8]}",
        venue_id=venue_id,
        scheduled_at=now,
        scheduled_end_at=now + timedelta(hours=10),
        expected_guest_count=1600,
    )


def _drink(name: str) -> FullEventProductInput:
    return FullEventProductInput(
        name=name,
        product_type=ProductType.DRINK,
        category=ProductCategory.BASIC_COCKTAIL,
        unit=ProductUnit.BOTTLE,
        default_price_cents=1200,
        iva_pct=0.10,
    )


async def _count(session, model, tenant_id) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(model).where(
                model.tenant_id == tenant_id
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_create_full_happy_path():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            venue = await _make_venue(session, tenant.id)
            svc = EventService(session)
            payload = FullEventCreate(
                event=_event_create(venue.id),
                bars=[
                    FullEventBar(name="Main Bar", device_count=9, slesh_category="Bar"),
                    FullEventBar(name="Beer Bar", device_count=4, slesh_category="Bar"),
                ],
                products=[_drink("Gin Bombay 1L"), _drink("Vodka Grey Goose 1L")],
                menu=[
                    FullEventMenuItem(bar_index=0, product_index=0, price_cents=1200),
                    FullEventMenuItem(bar_index=0, product_index=1, price_cents=1200),
                    FullEventMenuItem(bar_index=1, product_index=0, price_cents=1000),
                ],
                allocations=[
                    FullEventAllocation(bar_index=0, product_index=0, qty=24),
                    FullEventAllocation(bar_index=0, product_index=1, qty=12),
                    FullEventAllocation(bar_index=1, product_index=0, qty=0),  # skipped
                ],
            )
            result = await svc.create_full(tenant.id, payload)

            assert result["bars_created"] == 2
            assert result["products_created"] == 2
            assert result["products_reused"] == 0
            assert result["menu_items_created"] == 3
            assert result["allocations_created"] == 2  # qty=0 skipped

            assert await _count(session, Bar, tenant.id) == 2
            assert await _count(session, Product, tenant.id) == 2
            assert await _count(session, EventProduct, tenant.id) == 3
            assert await _count(session, BarStock, tenant.id) == 2
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_create_full_reuses_existing_product():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            # Pre-existing catalog product
            existing = await make_product(session, tenant.id)

            venue = await _make_venue(session, tenant.id)
            svc = EventService(session)
            payload = FullEventCreate(
                event=_event_create(venue.id),
                bars=[FullEventBar(name="Main Bar")],
                products=[
                    FullEventProductInput(
                        name=existing.name,            # same name
                        product_type=existing.product_type,  # same type → reuse
                        category=ProductCategory.BASIC_COCKTAIL,
                        unit=ProductUnit.BOTTLE,
                    ),
                    _drink("Brand New Spirit 1L"),     # new → create
                ],
                allocations=[
                    FullEventAllocation(bar_index=0, product_index=0, qty=10),
                ],
            )
            result = await svc.create_full(tenant.id, payload)

            assert result["products_reused"] == 1
            assert result["products_created"] == 1
            # Catalog grew by exactly 1 (the new one), reused row not duplicated
            assert await _count(session, Product, tenant.id) == 2
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_create_full_rollback_on_bad_index():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            venue = await _make_venue(session, tenant.id)
            svc = EventService(session)
            payload = FullEventCreate(
                event=_event_create(venue.id),
                bars=[FullEventBar(name="Main Bar")],
                products=[_drink("Gin 1L")],
                menu=[
                    # bar_index 5 does not exist (only 1 bar)
                    FullEventMenuItem(bar_index=5, product_index=0, price_cents=1000),
                ],
            )
            with pytest.raises(FullEventValidationError) as exc:
                await svc.create_full(tenant.id, payload)
            assert any(e.section == "menu" for e in exc.value.errors)

            # Nothing persisted — no orphan event/bar/product
            from app.modules.events.models import Event
            assert await _count(session, Event, tenant.id) == 0
            assert await _count(session, Bar, tenant.id) == 0
            assert await _count(session, Product, tenant.id) == 0
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_create_full_duplicate_product_rejected():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            venue = await _make_venue(session, tenant.id)
            svc = EventService(session)
            payload = FullEventCreate(
                event=_event_create(venue.id),
                bars=[FullEventBar(name="Main Bar")],
                products=[_drink("Gin 1L"), _drink("Gin 1L")],  # dup name+type
            )
            with pytest.raises(FullEventValidationError) as exc:
                await svc.create_full(tenant.id, payload)
            assert any(
                e.section == "products" and "duplicate" in e.error
                for e in exc.value.errors
            )
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_create_full_venue_not_found():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            svc = EventService(session)
            ev = _event_create(uuid.uuid4())  # nonexistent venue
            payload = FullEventCreate(event=ev, bars=[], products=[])
            with pytest.raises(VenueNotFoundError):
                await svc.create_full(tenant.id, payload)
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_update_full_replaces_children():
    """update_full replaces bars/menu/allocations; catalog products persist."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            venue = await _make_venue(session, tenant.id)
            svc = EventService(session)
            created = await svc.create_full(tenant.id, FullEventCreate(
                event=_event_create(venue.id),
                bars=[FullEventBar(name="Bar A"), FullEventBar(name="Bar B")],
                products=[_drink("Gin 1L"), _drink("Vodka 1L")],
                menu=[
                    FullEventMenuItem(bar_index=0, product_index=0, price_cents=1200),
                    FullEventMenuItem(bar_index=1, product_index=1, price_cents=1000),
                ],
                allocations=[FullEventAllocation(bar_index=0, product_index=0, qty=10)],
            ))
            event_id = created["event"].id

            # Restructure: 1 bar, 1 new product
            res = await svc.update_full(tenant.id, event_id, FullEventCreate(
                event=_event_create(venue.id),
                bars=[FullEventBar(name="Bar C")],
                products=[_drink("Rum 1L")],
                menu=[FullEventMenuItem(bar_index=0, product_index=0, price_cents=900)],
                allocations=[FullEventAllocation(bar_index=0, product_index=0, qty=5)],
            ))
            assert res["bars_created"] == 1
            from app.modules.events.models import Event
            assert await _count(session, Bar, tenant.id) == 1            # replaced
            assert await _count(session, EventProduct, tenant.id) == 1   # replaced
            assert await _count(session, BarStock, tenant.id) == 1       # replaced
            assert await _count(session, Product, tenant.id) == 3        # catalog persists (2+1)
            assert await _count(session, Event, tenant.id) == 1          # same event
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_update_full_rejects_non_draft():
    """Only DRAFT events can be restructured via the wizard."""
    from app.modules.events.models import EventStatus
    from app.modules.events.service import EventNotDraftError
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            venue = await _make_venue(session, tenant.id)
            svc = EventService(session)
            created = await svc.create_full(tenant.id, FullEventCreate(
                event=_event_create(venue.id),
                bars=[FullEventBar(name="Bar A")],
                products=[_drink("Gin 1L")],
            ))
            event = created["event"]
            event.status = EventStatus.LIVE
            await session.commit()

            with pytest.raises(EventNotDraftError):
                await svc.update_full(tenant.id, event.id, FullEventCreate(
                    event=_event_create(venue.id),
                    bars=[FullEventBar(name="Bar B")],
                    products=[_drink("Vodka 1L")],
                ))
        finally:
            await delete_tenant_cascade(session, tenant.id)
