"""Integration tests for the Day 4 customer-intelligence panel's service
layer, on real Postgres (TestSessionLocal, local dev DB — never
production, see tests/fixtures/alerts/session.py).

Live guest/spend stats are built from event_orders directly (NOT
customer_sessions/customer_purchases, which are offline-batch tables
and would be empty for a currently-LIVE event) — these tests seed
event_orders + stock_transactions directly, mirroring
test_build_customer_features.py's _make_identified_order pattern.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.modules.customer_intelligence.constants import LIGHT_SPEND_MAX_CENTS, WHALE_SPEND_MIN_CENTS
from app.modules.customer_intelligence.service import (
    EventNotFoundError,
    EventNotInTenantError,
    get_customer_intelligence,
    set_hot_night_override,
)
from app.modules.customer_analytics.models import CustomerSession
from app.modules.events.models import Event, EventOrder, EventStatus
from app.modules.predictions.demand import loader as loader_module
from app.modules.predictions.demand.retrain import retrain_demand_model
from app.modules.products.models import ProductCategory, ProductType
from app.modules.stock_transactions.models import TransactionSource
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_bar,
    make_event,
    make_product,
    make_stock_transaction,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

T0 = datetime(2026, 8, 2, 20, 0, tzinfo=timezone.utc)  # a stable "doors open" anchor


@pytest.fixture(autouse=True)
def _clear_loader_cache():
    loader_module._cache.clear()
    yield
    loader_module._cache.clear()


async def _order(session, *, tenant_id, event_id, slesh_order_id, user_id,
                  customer_email=None, fiscal_gross_cents=1000, created_at_slesh=T0):
    order = EventOrder(
        tenant_id=tenant_id, event_id=event_id, slesh_order_id=slesh_order_id,
        order_type="experience", cart_line_count=1, confirmed_line_count=1, refunded_line_count=0,
        raw_extras={"user": {"_id": user_id}}, customer_email=customer_email,
        fiscal_gross_cents=fiscal_gross_cents, created_at_slesh=created_at_slesh,
    )
    session.add(order)
    await session.flush()
    return order


async def _line(session, tenant_id, event_id, bar, product, order, *, line_id="line-1"):
    return await make_stock_transaction(
        session, tenant_id, event_id, bar.id, product.id,
        source=TransactionSource.SLESH_POS,
        idempotency_key=f"slesh:{order.slesh_order_id}:{line_id}",
    )


@pytest.mark.asyncio
async def test_guest_stats_and_spend_segments():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id, status=EventStatus.LIVE)

        await _order(session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-whale",
                     user_id="u-whale", customer_email="whale@gmail.com", fiscal_gross_cents=WHALE_SPEND_MIN_CENTS)
        await _order(session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-light",
                     user_id="u-light", customer_email="light@slesh.it", fiscal_gross_cents=LIGHT_SPEND_MAX_CENTS)
        await _order(session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-regular",
                     user_id="u-regular", customer_email=None, fiscal_gross_cents=4000)
        await session.commit()

        result = await get_customer_intelligence(session, tenant.id, event.id, T0 + timedelta(hours=1))

        assert result.guests.live_identified_count == 3
        assert result.guests.registered_count == 1   # gmail.com
        assert result.guests.guest_count == 1         # slesh.it domain
        assert result.guests.unknown_count == 1        # no email at all

        assert result.spend_segments.whale_count == 1
        assert result.spend_segments.light_count == 1
        assert result.spend_segments.regular_count == 1
        assert result.spend_segments.whale_threshold_cents == WHALE_SPEND_MIN_CENTS
        assert result.spend_segments.light_threshold_cents == LIGHT_SPEND_MAX_CENTS

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_returning_guests_recognized_from_prior_identity_event():
    from app.modules.customer_intelligence.constants import IDENTITY_EVENT_IDS

    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id, status=EventStatus.LIVE)

        returning_key = "u-returning"
        new_key = "u-new"
        await _order(session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-1",
                     user_id=returning_key, fiscal_gross_cents=1000)
        await _order(session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-2",
                     user_id=new_key, fiscal_gross_cents=1000)

        # CustomerSession.event_id FKs to events.id, so a prior identity
        # event's customer_sessions row needs a real local Event row
        # under that exact id -- create one matching one of the real
        # IDENTITY_EVENT_IDS constants (same pattern as the Jul-5
        # regression test in test_demand_retrain.py).
        prior_event_id = next(iter(IDENTITY_EVENT_IDS))
        prior_event = Event(
            id=prior_event_id, tenant_id=tenant.id, venue_id=event.venue_id,
            name="prior-identity-event", status=EventStatus.COMPLETED,
            expected_guest_count=100, scheduled_at=T0 - timedelta(days=30),
            scheduled_end_at=T0 - timedelta(days=30) + timedelta(hours=8), version=1,
        )
        session.add(prior_event)
        await session.flush()
        session.add(CustomerSession(
            tenant_id=tenant.id, event_id=prior_event_id, customer_key=returning_key,
            first_order_at=T0 - timedelta(days=30), last_order_at=T0 - timedelta(days=30),
            session_minutes=Decimal("10"), order_count=1, total_spend_cents=1000, avg_order_cents=1000,
            distinct_bars=1, orders_with_lines=1, has_full_line_coverage=True,
        ))
        await session.commit()

        result = await get_customer_intelligence(session, tenant.id, event.id, T0 + timedelta(hours=1))
        assert result.returning_guests.identified_total == 2
        assert result.returning_guests.returning_count == 1
        assert result.returning_guests.new_count == 1

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_before_doors_open_empty_state():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id, status=EventStatus.LIVE)

        result = await get_customer_intelligence(session, tenant.id, event.id, T0)

        assert result.hour_offset_from_start is None
        assert result.guests.live_identified_count == 0
        assert result.demand_forecast.available is False
        assert "doors" in result.demand_forecast.unavailable_reason
        assert result.predicted_vs_actual == []

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_demand_forecast_unavailable_when_model_untrained():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id, status=EventStatus.LIVE)
        bar = await make_bar(session, tenant.id, event.id)
        beer = await make_product(session, tenant.id, product_type=ProductType.DRINK,
                                   category=ProductCategory.BEER_DRAFT, name="Birra")
        order = await _order(session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-1",
                              user_id="u-1", fiscal_gross_cents=1000)
        await session.flush()
        await _line(session, tenant.id, event.id, bar, beer, order, line_id="l1")
        await session.commit()

        result = await get_customer_intelligence(session, tenant.id, event.id, T0 + timedelta(hours=1))
        assert result.demand_forecast.available is False
        assert "not yet trained" in result.demand_forecast.unavailable_reason
        # live guest stats still render despite the missing model
        assert result.guests.live_identified_count == 1

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_demand_forecast_distinguishes_artifact_unavailable_from_untrained(tmp_path):
    """The Jul-30 production incident, reproduced end-to-end: a model
    WAS trained (an active row exists) but its payload can't be loaded
    -- the panel must say so distinctly, not "not yet trained"."""
    from app.modules.predictions.demand.retrain import retrain_demand_model
    from app.modules.predictions.models import ModelArtifact

    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        await retrain_demand_model(session, tenant.id, triggered_by="test", artifacts_dir=tmp_path)
        await session.execute(
            ModelArtifact.__table__.update()
            .where(ModelArtifact.tenant_id == tenant.id)
            .values(file_bytes=None, file_path="/nonexistent/path.pkl")
        )
        await session.commit()

        event = await make_event(session, tenant.id, status=EventStatus.LIVE)
        bar = await make_bar(session, tenant.id, event.id)
        beer = await make_product(session, tenant.id, product_type=ProductType.DRINK,
                                   category=ProductCategory.BEER_DRAFT, name="Birra")
        order = await _order(session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-1",
                              user_id="u-1", fiscal_gross_cents=1000)
        await session.flush()
        await _line(session, tenant.id, event.id, bar, beer, order, line_id="l1")
        await session.commit()

        result = await get_customer_intelligence(session, tenant.id, event.id, T0 + timedelta(hours=1))
        assert result.demand_forecast.available is False
        assert result.demand_forecast.unavailable_reason == "model artifact unavailable"
        assert "not yet trained" not in result.demand_forecast.unavailable_reason
        assert result.guests.live_identified_count == 1

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_demand_forecast_available_with_next_hour_band_and_low_confidence_flags(tmp_path):
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        await retrain_demand_model(session, tenant.id, triggered_by="test", artifacts_dir=tmp_path)

        event = await make_event(session, tenant.id, status=EventStatus.LIVE)
        bar = await make_bar(session, tenant.id, event.id)
        beer = await make_product(session, tenant.id, product_type=ProductType.DRINK,
                                   category=ProductCategory.BEER_DRAFT, name="Birra")
        spritz = await make_product(session, tenant.id, product_type=ProductType.DRINK,
                                     category=ProductCategory.BASIC_COCKTAIL, name="Spritz Aperol")
        deposit = await make_product(session, tenant.id, product_type=ProductType.DRINK,
                                      category=ProductCategory.BASIC_COCKTAIL, name="Bicchiere")

        order = await _order(session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-1",
                              user_id="u-1", fiscal_gross_cents=3000, created_at_slesh=T0)
        await session.flush()
        await _line(session, tenant.id, event.id, bar, beer, order, line_id="l1")
        await _line(session, tenant.id, event.id, bar, spritz, order, line_id="l2")
        await _line(session, tenant.id, event.id, bar, deposit, order, line_id="l3")
        await session.commit()

        result = await get_customer_intelligence(session, tenant.id, event.id, T0 + timedelta(hours=1))

        assert result.demand_forecast.available is True
        assert result.demand_forecast.confidence_interval is not None
        assert result.demand_forecast.next_hour is not None
        nh = result.demand_forecast.next_hour
        assert nh.confidence_interval.lower <= nh.predicted_total <= nh.confidence_interval.upper
        cats = {c.category: c for c in nh.category_breakdown}
        assert cats["spritz"].low_confidence is True
        assert cats["cocktail"].low_confidence is True
        assert cats["beer"].low_confidence is False
        # deposit line excluded from the drinks grid entirely
        assert set(cats.keys()) <= {"beer", "cocktail", "spritz", "wine", "premium", "other"}

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_predicted_vs_actual_covers_only_closed_hours(tmp_path):
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        await retrain_demand_model(session, tenant.id, triggered_by="test", artifacts_dir=tmp_path)

        event = await make_event(session, tenant.id, status=EventStatus.LIVE)
        bar = await make_bar(session, tenant.id, event.id)
        beer = await make_product(session, tenant.id, product_type=ProductType.DRINK,
                                   category=ProductCategory.BEER_DRAFT, name="Birra")

        # One order at hour 0, one at hour 2 -- as_of_time is 2.5h in, so
        # only hours 1 and 2 have fully closed (hour 0 is never "target",
        # per the checkpoint protocol -- see service.py).
        o1 = await _order(session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-1",
                           user_id="u-1", created_at_slesh=T0)
        o2 = await _order(session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-2",
                           user_id="u-2", created_at_slesh=T0 + timedelta(hours=2))
        await session.flush()
        await _line(session, tenant.id, event.id, bar, beer, o1, line_id="l1")
        await _line(session, tenant.id, event.id, bar, beer, o2, line_id="l1")
        await session.commit()

        result = await get_customer_intelligence(session, tenant.id, event.id, T0 + timedelta(hours=2, minutes=30))

        hours_covered = {p.hour_of_event for p in result.predicted_vs_actual}
        assert hours_covered == {1.0, 2.0}
        by_hour = {p.hour_of_event: p for p in result.predicted_vs_actual}
        assert by_hour[2.0].actual == 1.0  # the hour-2 order
        assert by_hour[1.0].actual == 0.0  # nothing landed in hour 1

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_hot_night_override_toggle_persists_and_affects_forecast(tmp_path):
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        await retrain_demand_model(session, tenant.id, triggered_by="test", artifacts_dir=tmp_path)
        event = await make_event(session, tenant.id, status=EventStatus.LIVE)
        assert event.hot_night_override is False

        updated = await set_hot_night_override(session, tenant.id, event.id, True)
        assert updated.hot_night_override is True

        order = await _order(session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-1",
                              user_id="u-1", created_at_slesh=T0)
        bar = await make_bar(session, tenant.id, event.id)
        beer = await make_product(session, tenant.id, product_type=ProductType.DRINK,
                                   category=ProductCategory.BEER_DRAFT, name="Birra")
        await _line(session, tenant.id, event.id, bar, beer, order, line_id="l1")
        await session.commit()

        result = await get_customer_intelligence(session, tenant.id, event.id, T0 + timedelta(hours=1))
        assert result.hot_night_override is True
        assert result.demand_forecast.hot_night_applied is True

        await delete_tenant_cascade(session, tenant.id)


@pytest.mark.asyncio
async def test_event_not_found_and_wrong_tenant_raise():
    import uuid
    async with TestSessionLocal() as session:
        tenant_a = await make_tenant(session)
        tenant_b = await make_tenant(session)
        event = await make_event(session, tenant_a.id, status=EventStatus.LIVE)
        await session.commit()

        with pytest.raises(EventNotFoundError):
            await get_customer_intelligence(session, tenant_a.id, uuid.uuid4(), T0)

        with pytest.raises(EventNotInTenantError):
            await get_customer_intelligence(session, tenant_b.id, event.id, T0)

        await delete_tenant_cascade(session, tenant_a.id)
        await delete_tenant_cascade(session, tenant_b.id)
