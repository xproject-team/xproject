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
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.bar_stock.models import BarStock
from app.modules.bars.models import Bar
from app.modules.chat.models import Channel, ChatMessage
from app.modules.event_products.models import EventProduct
from app.modules.event_storage.models import (
    EventCategoryIngredient,
    EventStockBarAllocation,
    SupplierProduct,
)
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
    FoodType,
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


async def _make_supplier_product(session, tenant_id) -> SupplierProduct:
    sp = SupplierProduct(
        tenant_id=tenant_id,
        supplier_name="Partesa",
        supplier_sku=f"SKU-{uuid.uuid4().hex[:8]}",
        item_name=f"Test Item {uuid.uuid4().hex[:6]}",
        category="gin",
        default_unit="BO",
        units_per_pack=1,
    )
    session.add(sp)
    await session.flush()
    return sp


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


# ─── Day 9B: update-in-place (bug fix for silent recipe/dispatch/chat loss) ──

@pytest.mark.asyncio
async def test_update_full_preserves_recipes_for_matched_bar():
    """A bar with the same (normalised) name across an edit keeps its id,
    so its event_category_ingredients rows are never touched — this is
    the Day 9B fix: editing bars used to CASCADE-delete these silently."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            venue = await _make_venue(session, tenant.id)
            svc = EventService(session)
            created = await svc.create_full(tenant.id, FullEventCreate(
                event=_event_create(venue.id),
                bars=[FullEventBar(name="Main Bar")],
                products=[_drink("Gin 1L")],
            ))
            event_id = created["event"].id
            bar = (
                await session.execute(select(Bar).where(Bar.event_id == event_id))
            ).scalars().one()
            original_bar_id = bar.id

            sp = await _make_supplier_product(session, tenant.id)
            eci = EventCategoryIngredient(
                tenant_id=tenant.id, event_id=event_id, slesh_category="SPRITZ",
                supplier_product_id=sp.id, bar_id=original_bar_id,
                ml_per_sale=Decimal("40.00"),
            )
            session.add(eci)
            await session.flush()
            eci_id = eci.id

            # Edit-mode save changing an unrelated field, same bar name.
            ev = _event_create(venue.id)
            ev.expected_guest_count = 2000
            await svc.update_full(tenant.id, event_id, FullEventCreate(
                event=ev,
                bars=[FullEventBar(name="Main Bar")],
                products=[_drink("Gin 1L")],
            ))

            surviving_bar = (
                await session.execute(select(Bar).where(Bar.event_id == event_id))
            ).scalars().one()
            assert surviving_bar.id == original_bar_id  # updated in place, not recreated

            surviving_eci = (
                await session.execute(
                    select(EventCategoryIngredient).where(EventCategoryIngredient.id == eci_id)
                )
            ).scalar_one_or_none()
            assert surviving_eci is not None
            assert surviving_eci.bar_id == original_bar_id
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_update_full_preserves_dispatch_for_matched_bar():
    """Same shape as the recipes test, for event_stock_bar_allocations
    (warehouse dispatch) — the second table this bug was silently destroying."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            venue = await _make_venue(session, tenant.id)
            svc = EventService(session)
            created = await svc.create_full(tenant.id, FullEventCreate(
                event=_event_create(venue.id),
                bars=[FullEventBar(name="Main Bar")],
                products=[_drink("Gin 1L")],
            ))
            event_id = created["event"].id
            bar = (
                await session.execute(select(Bar).where(Bar.event_id == event_id))
            ).scalars().one()
            original_bar_id = bar.id

            sp = await _make_supplier_product(session, tenant.id)
            dispatch = EventStockBarAllocation(
                tenant_id=tenant.id, event_id=event_id,
                supplier_product_id=sp.id, bar_id=original_bar_id,
                qty_allocated=Decimal("24.00"),
            )
            session.add(dispatch)
            await session.flush()
            dispatch_id = dispatch.id

            ev = _event_create(venue.id)
            ev.expected_guest_count = 2000
            await svc.update_full(tenant.id, event_id, FullEventCreate(
                event=ev,
                bars=[FullEventBar(name="Main Bar")],
                products=[_drink("Gin 1L")],
            ))

            surviving = (
                await session.execute(
                    select(EventStockBarAllocation).where(
                        EventStockBarAllocation.id == dispatch_id
                    )
                )
            ).scalar_one_or_none()
            assert surviving is not None
            assert surviving.bar_id == original_bar_id
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_update_full_preserves_chat_and_does_not_duplicate_channel():
    """A matched bar's chat channel (auto-created by create_full) and its
    messages survive an edit; the edit must not create a second channel
    for the same bar."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            venue = await _make_venue(session, tenant.id)
            svc = EventService(session)
            created = await svc.create_full(tenant.id, FullEventCreate(
                event=_event_create(venue.id),
                bars=[FullEventBar(name="Main Bar")],
                products=[_drink("Gin 1L")],
            ))
            event_id = created["event"].id
            bar = (
                await session.execute(select(Bar).where(Bar.event_id == event_id))
            ).scalars().one()
            original_bar_id = bar.id

            channel = (
                await session.execute(
                    select(Channel).where(Channel.bar_id == original_bar_id)
                )
            ).scalar_one()
            message = ChatMessage(
                tenant_id=tenant.id, channel_id=channel.id, body="hello team",
            )
            session.add(message)
            await session.flush()
            message_id = message.id

            ev = _event_create(venue.id)
            ev.expected_guest_count = 2000
            await svc.update_full(tenant.id, event_id, FullEventCreate(
                event=ev,
                bars=[FullEventBar(name="Main Bar")],
                products=[_drink("Gin 1L")],
            ))

            channels = (
                await session.execute(
                    select(Channel).where(Channel.bar_id == original_bar_id)
                )
            ).scalars().all()
            assert len(channels) == 1  # no duplicate

            surviving_message = (
                await session.execute(
                    select(ChatMessage).where(ChatMessage.id == message_id)
                )
            ).scalar_one_or_none()
            assert surviving_message is not None
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_update_full_removed_bar_deletes_its_recipes():
    """A bar genuinely absent from the new payload is deleted, and its
    event_category_ingredients rows correctly cascade away with it — that
    data belongs to a bar that no longer exists."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            venue = await _make_venue(session, tenant.id)
            svc = EventService(session)
            created = await svc.create_full(tenant.id, FullEventCreate(
                event=_event_create(venue.id),
                bars=[FullEventBar(name="Main Bar"), FullEventBar(name="Beer Bar")],
                products=[_drink("Gin 1L")],
            ))
            event_id = created["event"].id
            bars = (
                await session.execute(select(Bar).where(Bar.event_id == event_id))
            ).scalars().all()
            beer_bar = next(b for b in bars if b.name == "Beer Bar")

            sp = await _make_supplier_product(session, tenant.id)
            eci = EventCategoryIngredient(
                tenant_id=tenant.id, event_id=event_id, slesh_category="BEER",
                supplier_product_id=sp.id, bar_id=beer_bar.id,
                ml_per_sale=Decimal("330.00"),
            )
            session.add(eci)
            await session.flush()
            eci_id = eci.id

            # Beer Bar is genuinely removed from the new payload.
            await svc.update_full(tenant.id, event_id, FullEventCreate(
                event=_event_create(venue.id),
                bars=[FullEventBar(name="Main Bar")],
                products=[_drink("Gin 1L")],
            ))

            assert await _count(session, Bar, tenant.id) == 1
            surviving = (
                await session.execute(
                    select(EventCategoryIngredient).where(EventCategoryIngredient.id == eci_id)
                )
            ).scalar_one_or_none()
            assert surviving is None  # correctly cascaded away with its bar
        finally:
            await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_update_full_rebuilds_menu_and_allocations_for_matched_bar():
    """event_products/bar_stock are still fully replaced on every save for a
    matched (kept) bar — only the unintended cascades were prevented."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            venue = await _make_venue(session, tenant.id)
            svc = EventService(session)
            created = await svc.create_full(tenant.id, FullEventCreate(
                event=_event_create(venue.id),
                bars=[FullEventBar(name="Main Bar")],
                products=[_drink("Gin 1L"), _drink("Vodka 1L")],
                menu=[FullEventMenuItem(bar_index=0, product_index=0, price_cents=1200)],
                allocations=[FullEventAllocation(bar_index=0, product_index=0, qty=10)],
            ))
            event_id = created["event"].id
            bar = (
                await session.execute(select(Bar).where(Bar.event_id == event_id))
            ).scalars().one()
            original_bar_id = bar.id

            old_menu = (
                await session.execute(
                    select(EventProduct).where(EventProduct.bar_id == original_bar_id)
                )
            ).scalars().all()
            assert len(old_menu) == 1
            old_menu_id = old_menu[0].id

            # Same bar, different menu/allocation content.
            res = await svc.update_full(tenant.id, event_id, FullEventCreate(
                event=_event_create(venue.id),
                bars=[FullEventBar(name="Main Bar")],
                products=[_drink("Gin 1L"), _drink("Vodka 1L")],
                menu=[FullEventMenuItem(bar_index=0, product_index=1, price_cents=1500)],
                allocations=[FullEventAllocation(bar_index=0, product_index=1, qty=6)],
            ))

            surviving_bar = (
                await session.execute(select(Bar).where(Bar.event_id == event_id))
            ).scalars().one()
            assert surviving_bar.id == original_bar_id  # still matched, not recreated

            new_menu = (
                await session.execute(
                    select(EventProduct).where(EventProduct.bar_id == original_bar_id)
                )
            ).scalars().all()
            assert len(new_menu) == 1
            assert new_menu[0].id != old_menu_id  # rebuilt, not the same row
            assert new_menu[0].price_cents == 1500

            new_stock = (
                await session.execute(
                    select(BarStock).where(BarStock.bar_id == original_bar_id)
                )
            ).scalars().all()
            assert len(new_stock) == 1
            assert new_stock[0].allocated_qty == 6
            assert res["bars_updated"] == 1
            assert res["bars_created"] == 0
        finally:
            await delete_tenant_cascade(session, tenant.id)


def _food(name, food_type):
    return FullEventProductInput(
        name=name,
        product_type=ProductType.FOOD,
        unit=ProductUnit.PIECE,
        default_price_cents=1200,
        iva_pct=0.10,
        food_type=food_type,
    )


@pytest.mark.asyncio
async def test_create_full_persists_food_type_and_share():
    """food_type (per product) + food_revenue_share_pct (per event) round-trip."""
    from app.modules.events.models import Event
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            venue = await _make_venue(session, tenant.id)
            svc = EventService(session)
            ev = _event_create(venue.id)
            ev.food_revenue_share_pct = 30
            payload = FullEventCreate(
                event=ev,
                bars=[
                    FullEventBar(name="Cocktail Bar"),
                    FullEventBar(name="Food Truck", bar_type="food"),
                ],
                products=[_drink("Gin Tonic"), _food("Hamburger", FoodType.BURGERS)],
                menu=[
                    FullEventMenuItem(bar_index=0, product_index=0, price_cents=1200),
                    FullEventMenuItem(bar_index=1, product_index=1, price_cents=1200),
                ],
                allocations=[
                    FullEventAllocation(bar_index=1, product_index=1, qty=50),
                ],
            )
            result = await svc.create_full(tenant.id, payload)
            event_id = result["event"].id

            ev_row = (
                await session.execute(select(Event).where(Event.id == event_id))
            ).scalar_one()
            assert ev_row.food_revenue_share_pct == 30

            food = (
                await session.execute(
                    select(Product).where(
                        Product.tenant_id == tenant.id,
                        Product.product_type == ProductType.FOOD,
                    )
                )
            ).scalar_one()
            assert food.food_type == FoodType.BURGERS

            drink = (
                await session.execute(
                    select(Product).where(
                        Product.tenant_id == tenant.id,
                        Product.product_type == ProductType.DRINK,
                    )
                )
            ).scalar_one()
            assert drink.food_type is None
        finally:
            await delete_tenant_cascade(session, tenant.id)
