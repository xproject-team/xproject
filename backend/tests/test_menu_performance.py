"""Menu-performance tests (dashboard breakdown panel aggregator).

Covers MenuPerformanceService.get_for_event:
  - drinks totalled per product ACROSS bars, grouped by family; zero-sold
    menu items still appear
  - food grouped by truck (bar); zero-sold items appear; trucks ordered
    busiest-first
  - non drink/food menu lines (supply/deposit) excluded
  - unknown event -> None
  - empty menu -> empty groups
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.event_products.models import EventProduct
from app.modules.events.menu_performance_service import MenuPerformanceService
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

pytestmark = pytest.mark.asyncio
_REVENUE_SOURCE = TransactionSource(REVENUE_SOURCES[0])


async def _menu(session, tenant_id, event_id, bar_id, product_id, *, price_cents=1000):
    ep = EventProduct(
        tenant_id=tenant_id, event_id=event_id, bar_id=bar_id,
        product_id=product_id, price_cents=price_cents, is_available=True,
    )
    session.add(ep)
    await session.flush()
    return ep


async def _drink(session, tenant_id, category, name):
    p = await make_product(session, tenant_id, product_type=ProductType.DRINK)
    p.category = category
    p.food_type = None
    p.name = name
    await session.flush()
    return p


async def _food(session, tenant_id, food_type, name):
    p = await make_product(session, tenant_id, product_type=ProductType.FOOD)
    p.category = None
    p.food_type = food_type
    p.name = name
    await session.flush()
    return p


async def _sale(session, tenant_id, event_id, bar_id, product_id, *, qty, price_cents):
    st = await make_stock_transaction(
        session, tenant_id, event_id, bar_id, product_id,
        qty=Decimal(str(qty)), source=_REVENUE_SOURCE,
    )
    st.price_cents = price_cents
    await session.flush()
    return st


async def test_drinks_totalled_across_bars_and_zero_sold():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            bar1 = await make_bar(session, tenant.id, ev.id)
            bar2 = await make_bar(session, tenant.id, ev.id)
            gin = await _drink(session, tenant.id, ProductCategory.BASIC_COCKTAIL, "Gin Tonic")
            spritz = await _drink(session, tenant.id, ProductCategory.BASIC_COCKTAIL, "Spritz")
            beer = await _drink(session, tenant.id, ProductCategory.BEER_BOTTLE, "Heineken")
            # shared cocktail menu on both bars
            for b in (bar1, bar2):
                await _menu(session, tenant.id, ev.id, b.id, gin.id)
                await _menu(session, tenant.id, ev.id, b.id, spritz.id)
            await _menu(session, tenant.id, ev.id, bar1.id, beer.id)
            # sales: gin 5@bar1 + 3@bar2; beer 10@bar1; spritz unsold
            await _sale(session, tenant.id, ev.id, bar1.id, gin.id, qty=5, price_cents=1200)
            await _sale(session, tenant.id, ev.id, bar2.id, gin.id, qty=3, price_cents=1200)
            await _sale(session, tenant.id, ev.id, bar1.id, beer.id, qty=10, price_cents=700)

            res = await MenuPerformanceService(session).get_for_event(tenant.id, ev.id)
            assert res is not None
            fam = {g.family: g for g in res.drinks}
            assert set(fam) == {"cocktails", "beer"}
            cocktails = {i.product_name: i for i in fam["cocktails"].items}
            assert cocktails["Gin Tonic"].units == 8                 # 5 + 3 across bars
            assert cocktails["Gin Tonic"].revenue_eur == Decimal("96.00")
            assert cocktails["Spritz"].units == 0                    # zero-sold included
            assert fam["cocktails"].subtotal_units == 8
            assert {i.product_name: i.units for i in fam["beer"].items} == {"Heineken": 10}
            assert res.food == []
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_food_grouped_by_truck_with_zero_sold():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            truck_a = await make_bar(session, tenant.id, ev.id)
            truck_b = await make_bar(session, tenant.id, ev.id)
            burger = await _food(session, tenant.id, FoodType.BURGERS, "Burger")
            fries = await _food(session, tenant.id, FoodType.FRIED, "Fries")
            pizza = await _food(session, tenant.id, FoodType.PIZZA, "Pizza")
            await _menu(session, tenant.id, ev.id, truck_a.id, burger.id)
            await _menu(session, tenant.id, ev.id, truck_a.id, fries.id)
            await _menu(session, tenant.id, ev.id, truck_b.id, pizza.id)
            await _sale(session, tenant.id, ev.id, truck_a.id, burger.id, qty=4, price_cents=1200)
            await _sale(session, tenant.id, ev.id, truck_b.id, pizza.id, qty=7, price_cents=900)
            # fries unsold

            res = await MenuPerformanceService(session).get_for_event(tenant.id, ev.id)
            assert res.drinks == []
            assert len(res.food) == 2
            # busiest truck first: B (7) before A (4)
            assert res.food[0].bar_id == truck_b.id
            assert res.food[0].subtotal_units == 7
            assert {i.product_name: i.units for i in res.food[0].items} == {"Pizza": 7}
            a_group = next(g for g in res.food if g.bar_id == truck_a.id)
            a_items = {i.product_name: i.units for i in a_group.items}
            assert a_items == {"Burger": 4, "Fries": 0}              # zero-sold included
            assert a_group.subtotal_units == 4
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_excludes_non_drink_food():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            bar = await make_bar(session, tenant.id, ev.id)
            cocktail = await _drink(session, tenant.id, ProductCategory.BASIC_COCKTAIL, "Negroni")
            supply = await make_product(session, tenant.id, product_type=ProductType.SUPPLY)
            supply.name = "Cup Deposit"
            await session.flush()
            await _menu(session, tenant.id, ev.id, bar.id, cocktail.id)
            await _menu(session, tenant.id, ev.id, bar.id, supply.id)
            await _sale(session, tenant.id, ev.id, bar.id, cocktail.id, qty=2, price_cents=1000)
            await _sale(session, tenant.id, ev.id, bar.id, supply.id, qty=9, price_cents=100)

            res = await MenuPerformanceService(session).get_for_event(tenant.id, ev.id)
            all_names = [
                i.product_name
                for g in res.drinks for i in g.items
            ] + [
                i.product_name
                for g in res.food for i in g.items
            ]
            assert "Negroni" in all_names
            assert "Cup Deposit" not in all_names
            assert res.food == []
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_unknown_event_returns_none():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            res = await MenuPerformanceService(session).get_for_event(
                tenant.id, uuid.uuid4()
            )
            assert res is None
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()


async def test_empty_menu_returns_empty_groups():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            ev = await make_event(session, tenant.id)
            res = await MenuPerformanceService(session).get_for_event(tenant.id, ev.id)
            assert res is not None
            assert res.drinks == []
            assert res.food == []
        finally:
            await delete_tenant_cascade(session, tenant.id)
            await session.commit()
