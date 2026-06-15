"""Event-level KPI summary tests (dashboard top-strip aggregator).

Covers EventKpiSummaryService.get_for_event:
  - drinks-only, families roll up (cocktails/beer/wine/soft); NULL share = 100%
  - food-only, share applied (50%)
  - mixed drinks + food, Sundance-like 30% split
  - share = 0 (food company keeps all) -> food net = 0
  - share = 100 explicit -> food net == gross
  - empty event -> zeroed summary (NOT None)
  - unknown event -> None (404 path)
  - non-revenue source AND price_cents IS NULL rows are excluded

Service-level, same fixture style as test_create_full_event.py. Every test
cleans up via delete_tenant_cascade in a finally block.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.events.event_kpi_service import EventKpiSummaryService
from app.modules.predictions.predictors.heuristic import REVENUE_SOURCES
from app.modules.products.models import FoodType, ProductCategory, ProductType
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

_REVENUE_SOURCE = TransactionSource(REVENUE_SOURCES[0])  # "slesh_pos"

pytestmark = pytest.mark.asyncio


# ── helpers ───────────────────────────────────────────────────────────────────

async def _drink_product(session, tenant_id, category):
    p = await make_product(session, tenant_id, product_type=ProductType.DRINK)
    p.category = category
    p.food_type = None
    await session.flush()
    return p


async def _food_product(session, tenant_id, food_type):
    p = await make_product(session, tenant_id, product_type=ProductType.FOOD)
    p.category = None
    p.food_type = food_type
    await session.flush()
    return p


async def _sale(session, tenant_id, event_id, bar_id, product_id, *, qty, price_cents):
    """A revenue-producing line: slesh_pos source + a per-unit price."""
    st = await make_stock_transaction(
        session, tenant_id, event_id, bar_id, product_id,
        qty=Decimal(str(qty)),
        source=_REVENUE_SOURCE,
    )
    st.price_cents = price_cents
    await session.flush()
    return st


# ── tests ───────────────────────────────────────────────────────────────────

async def test_drinks_only_families_null_share_is_100():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)          # share defaults to None
            bar = await make_bar(session, tenant.id, ev.id)
            beer = await _drink_product(session, tenant.id, ProductCategory.BEER_BOTTLE)
            wine = await _drink_product(session, tenant.id, ProductCategory.WINE_RED)
            cock = await _drink_product(session, tenant.id, ProductCategory.BASIC_COCKTAIL)
            soft = await _drink_product(session, tenant.id, ProductCategory.SOFT_DRINK)
            await _sale(session, tenant.id, ev.id, bar.id, beer.id, qty=2, price_cents=700)
            await _sale(session, tenant.id, ev.id, bar.id, wine.id, qty=3, price_cents=700)
            await _sale(session, tenant.id, ev.id, bar.id, cock.id, qty=1, price_cents=1200)
            await _sale(session, tenant.id, ev.id, bar.id, soft.id, qty=5, price_cents=600)

            res = await EventKpiSummaryService(session).get_for_event(tenant.id, ev.id)
            assert res is not None
            assert res.drinks.units == 11
            assert res.drinks.revenue_eur == Decimal("77.00")
            fams = {ln.family: ln for ln in res.drinks.by_category}
            assert (fams["beer"].units, fams["beer"].revenue_eur) == (2, Decimal("14.00"))
            assert (fams["wine"].units, fams["wine"].revenue_eur) == (3, Decimal("21.00"))
            assert (fams["cocktails"].units, fams["cocktails"].revenue_eur) == (1, Decimal("12.00"))
            assert (fams["soft"].units, fams["soft"].revenue_eur) == (5, Decimal("30.00"))
            assert res.food.units == 0
            assert res.food.gross_revenue_eur == Decimal("0.00")
            assert res.food.net_revenue_eur == Decimal("0.00")
            assert res.food.share_pct == 100          # NULL -> 100
            assert res.food.by_type == []
            assert res.total_revenue_eur == Decimal("77.00")
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_food_only_share_50():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            ev.food_revenue_share_pct = 50
            await session.flush()
            bar = await make_bar(session, tenant.id, ev.id)
            burg = await _food_product(session, tenant.id, FoodType.BURGERS)
            gel = await _food_product(session, tenant.id, FoodType.GELATO)
            await _sale(session, tenant.id, ev.id, bar.id, burg.id, qty=4, price_cents=1200)
            await _sale(session, tenant.id, ev.id, bar.id, gel.id, qty=2, price_cents=500)

            res = await EventKpiSummaryService(session).get_for_event(tenant.id, ev.id)
            assert res.drinks.units == 0
            assert res.drinks.revenue_eur == Decimal("0.00")
            assert res.drinks.by_category == []
            assert res.food.units == 6
            assert res.food.gross_revenue_eur == Decimal("58.00")
            assert res.food.share_pct == 50
            assert res.food.net_revenue_eur == Decimal("29.00")   # 58 * 50%
            ftypes = {ln.food_type: ln for ln in res.food.by_type}
            assert (ftypes["burgers"].units, ftypes["burgers"].revenue_eur) == (4, Decimal("48.00"))
            assert (ftypes["gelato"].units, ftypes["gelato"].revenue_eur) == (2, Decimal("10.00"))
            assert res.total_revenue_eur == Decimal("58.00")      # drinks 0 + food gross 58
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_mixed_share_30():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            ev.food_revenue_share_pct = 30
            await session.flush()
            bar = await make_bar(session, tenant.id, ev.id)
            cock = await _drink_product(session, tenant.id, ProductCategory.PREMIUM_COCKTAIL)
            burg = await _food_product(session, tenant.id, FoodType.BURGERS)
            await _sale(session, tenant.id, ev.id, bar.id, cock.id, qty=10, price_cents=1200)
            await _sale(session, tenant.id, ev.id, bar.id, burg.id, qty=5, price_cents=1200)

            res = await EventKpiSummaryService(session).get_for_event(tenant.id, ev.id)
            assert res.drinks.units == 10
            assert res.drinks.revenue_eur == Decimal("120.00")
            # premium_cocktail folds into the "cocktails" family
            fams = {ln.family: ln for ln in res.drinks.by_category}
            assert fams["cocktails"].units == 10
            assert res.food.units == 5
            assert res.food.gross_revenue_eur == Decimal("60.00")
            assert res.food.share_pct == 30
            assert res.food.net_revenue_eur == Decimal("18.00")   # 60 * 30%
            assert res.total_revenue_eur == Decimal("180.00")     # drinks 120 + food gross 60
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_share_zero_food_net_is_zero():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            ev.food_revenue_share_pct = 0
            await session.flush()
            bar = await make_bar(session, tenant.id, ev.id)
            cock = await _drink_product(session, tenant.id, ProductCategory.BASIC_COCKTAIL)
            burg = await _food_product(session, tenant.id, FoodType.BURGERS)
            await _sale(session, tenant.id, ev.id, bar.id, cock.id, qty=1, price_cents=1000)
            await _sale(session, tenant.id, ev.id, bar.id, burg.id, qty=3, price_cents=1000)

            res = await EventKpiSummaryService(session).get_for_event(tenant.id, ev.id)
            assert res.drinks.revenue_eur == Decimal("10.00")
            assert res.food.gross_revenue_eur == Decimal("30.00")
            assert res.food.share_pct == 0
            assert res.food.net_revenue_eur == Decimal("0.00")
            assert res.total_revenue_eur == Decimal("40.00")      # drinks 10 + food gross 30 (header = billed amount, not take-home)
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_share_explicit_100_equals_gross():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            ev.food_revenue_share_pct = 100
            await session.flush()
            bar = await make_bar(session, tenant.id, ev.id)
            burg = await _food_product(session, tenant.id, FoodType.SANDWICHES)
            await _sale(session, tenant.id, ev.id, bar.id, burg.id, qty=2, price_cents=1000)

            res = await EventKpiSummaryService(session).get_for_event(tenant.id, ev.id)
            assert res.food.share_pct == 100
            assert res.food.gross_revenue_eur == Decimal("20.00")
            assert res.food.net_revenue_eur == res.food.gross_revenue_eur
            assert res.total_revenue_eur == Decimal("20.00")
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_empty_event_returns_zeroed_summary():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)   # no bars, products, or sales
            res = await EventKpiSummaryService(session).get_for_event(tenant.id, ev.id)
            assert res is not None
            assert res.total_revenue_eur == Decimal("0.00")
            assert res.drinks.units == 0
            assert res.drinks.revenue_eur == Decimal("0.00")
            assert res.drinks.by_category == []
            assert res.food.units == 0
            assert res.food.gross_revenue_eur == Decimal("0.00")
            assert res.food.net_revenue_eur == Decimal("0.00")
            assert res.food.share_pct == 100
            assert res.food.by_type == []
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_unknown_event_returns_none():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            res = await EventKpiSummaryService(session).get_for_event(
                tenant.id, uuid.uuid4()
            )
            assert res is None
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_excludes_non_revenue_and_priceless_rows():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            bar = await make_bar(session, tenant.id, ev.id)
            cock = await _drink_product(session, tenant.id, ProductCategory.BASIC_COCKTAIL)

            # counted: revenue source + priced
            await _sale(session, tenant.id, ev.id, bar.id, cock.id, qty=2, price_cents=1000)
            # excluded: wrong source (factory default MANUAL_ADJUSTMENT) + no price
            await make_stock_transaction(
                session, tenant.id, ev.id, bar.id, cock.id, qty=Decimal("99"),
            )
            # excluded: revenue source but price_cents IS NULL (never set)
            await make_stock_transaction(
                session, tenant.id, ev.id, bar.id, cock.id, qty=Decimal("50"),
                source=_REVENUE_SOURCE,
            )

            res = await EventKpiSummaryService(session).get_for_event(tenant.id, ev.id)
            assert res.drinks.units == 2
            assert res.drinks.revenue_eur == Decimal("20.00")
            assert res.total_revenue_eur == Decimal("20.00")
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()
