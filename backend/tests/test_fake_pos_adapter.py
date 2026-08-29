"""FakePOSAdapter — provider-shaped payloads through the real pipeline.

The generator's data contract mirrors what was VERIFIED on production
during the revenue engagement (2026-08):

  - subtotal = fiscal_gross + deposit on EVERY order (held on
    15,387/15,387 production rows)
  - VAT computed on the deposit-INCLUSIVE subtotal, so net + vat is the
    subtotal, not the fiscal gross
  - order types "experience" (payment token) and "cash-desk" (payment
    mixed, no token, exact multiples of 1000 cents — the €10/head door
    admission at the service bar)
  - deposit products: Bicchiere 100c, Cauzione Bottiglia 200c
  - cart line status confirmed|refunded; refunded deposit returns occur
    inside otherwise-confirmed orders; a fully refunded order arrives
    with fiscal_gross = 0
  - a slice of orders reference a shop id with no matching bar, to
    exercise pending_shop_mappings parking
  - scale: 3000–4500 orders per event, whole-euro prices, average order
    ~12 EUR, peak hour 18:00 local

Written FIRST against the skeleton fake (which yields nothing), per the
failing-test rule.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.pos.adapters.fake import (
    FakePOSAdapter,
    GHOST_SHOP_ID,
    LOCAL_TZ,
)

pytestmark = pytest.mark.asyncio

# One full event window: 16:00 → 02:00 local (fixed +2 offset — see
# LOCAL_TZ in the adapter).
SINCE = datetime(2026, 9, 5, 16, 0, tzinfo=LOCAL_TZ)
UNTIL = datetime(2026, 9, 6, 2, 0, tzinfo=LOCAL_TZ)


async def _collect(adapter: FakePOSAdapter, **kwargs):
    orders = []
    async for o in adapter.list_orders(
        kwargs.pop("since_ts", SINCE), kwargs.pop("until_ts", UNTIL), **kwargs
    ):
        orders.append(o)
    return orders


def _confirmed_lines(order):
    return [ln for ln in order.cart if ln.status != "refunded"]


async def test_full_event_scale_shape_and_peak():
    async with FakePOSAdapter() as adapter:
        orders = await _collect(adapter, order_type=None)

    assert 3000 <= len(orders) <= 4500, f"got {len(orders)} orders"

    # Whole-euro line prices, everywhere.
    for o in orders:
        for ln in o.cart:
            assert ln.gross_amount % 100 == 0, (o.id, ln.id, ln.gross_amount)

    # Average order value ~12 EUR (confirmed amounts).
    totals = [o.subtotal for o in orders if o.subtotal]
    avg = sum(totals) / len(totals)
    assert 900 <= avg <= 1500, f"avg order {avg} cents"

    # Peak hour is 18:00 local.
    by_hour: dict[int, int] = {}
    for o in orders:
        local = datetime.fromtimestamp(o.created_at / 1000, tz=LOCAL_TZ)
        by_hour[local.hour] = by_hour.get(local.hour, 0) + 1
    peak = max(by_hour, key=by_hour.get)
    assert peak == 18, f"peak hour {peak}, distribution {by_hour}"

    # Ascending order, like the real adapter's sortDir=asc.
    assert all(a.created_at <= b.created_at for a, b in zip(orders, orders[1:]))


async def test_subtotal_identity_holds_on_every_order():
    """subtotal = fiscal_gross + deposit with NO exceptions, and VAT is
    computed on the deposit-inclusive subtotal (net + vat == subtotal,
    which differs from fiscal gross whenever a deposit exists)."""
    async with FakePOSAdapter() as adapter:
        orders = await _collect(adapter, order_type=None)

    assert orders
    saw_deposit = False
    for o in orders:
        subtotal = round(o.subtotal or 0)
        deposit = round(o.cart_deposit_amount or 0)
        fiscal_gross = round(o.cart_fiscal_gross_amount or 0)
        assert subtotal == fiscal_gross + deposit, (o.id, subtotal, fiscal_gross, deposit)

        vat = o.cart_vat_amount or 0.0
        net = o.cart_fiscal_net_amount or 0.0
        assert abs((net + vat) - (o.subtotal or 0)) < 0.01, (o.id, net, vat, o.subtotal)
        if deposit > 0:
            saw_deposit = True
            # net + vat covers the deposit-inclusive subtotal — NOT gross.
            assert round(net + vat) != fiscal_gross, o.id
    assert saw_deposit, "deposit-carrying orders must exist"


async def test_both_order_types_with_their_payment_shapes():
    async with FakePOSAdapter() as adapter:
        orders = await _collect(adapter, order_type=None)

    experience = [o for o in orders if o.type == "experience"]
    cash_desk = [o for o in orders if o.type == "cash-desk"]
    assert experience and cash_desk

    for o in cash_desk:
        assert o.payment is not None and o.payment.type == "mixed"
        assert o.payment.payment_token is None
        assert round(o.subtotal or 0) % 1000 == 0, (o.id, o.subtotal)
        assert round(o.cart_deposit_amount or 0) == 0

    tokened = [o for o in experience if o.payment and o.payment.type == "token"]
    assert tokened and all(o.payment.payment_token for o in tokened)

    # The default filter (order_type='experience') excludes cash-desk —
    # exactly what the live poller requests.
    async with FakePOSAdapter() as adapter:
        default_stream = await _collect(adapter)
    assert default_stream and all(o.type == "experience" for o in default_stream)


async def test_refunds_deposits_and_ghost_shop_present():
    async with FakePOSAdapter() as adapter:
        orders = await _collect(adapter, order_type=None)

    # Refunded deposit-return lines inside OTHERWISE-CONFIRMED orders are
    # deposit-priced only — production's entire refunded-line population
    # (422 lines) was Bicchiere/Cauzione returns. (A fully refunded order
    # refunds all its lines, whatever they are — asserted separately.)
    refunded_in_confirmed = [
        ln for o in orders if _confirmed_lines(o)
        for ln in o.cart if ln.status == "refunded"
    ]
    assert refunded_in_confirmed
    assert {ln.gross_amount for ln in refunded_in_confirmed} <= {100, 200}

    # Fully refunded orders arrive with fiscal_gross = 0.
    fully_refunded = [o for o in orders if o.cart and not _confirmed_lines(o)]
    assert fully_refunded
    for o in fully_refunded:
        assert round(o.cart_fiscal_gross_amount or 0) == 0
        assert round(o.subtotal or 0) == 0

    # Deposit lines at exactly 100c (Bicchiere) / 200c (Cauzione Bottiglia).
    deposit_lines = [
        ln for o in orders for ln in _confirmed_lines(o)
        if ln.gross_amount in (100, 200) and "cauzione" in str(ln.product_name).lower()
        or "bicchiere" in str(ln.product_name).lower()
    ]
    assert deposit_lines

    # At least one order references a shop with no matching bar.
    ghost_orders = [
        o for o in orders
        if o.shop is not None and not isinstance(o.shop, str) and o.shop.id == GHOST_SHOP_ID
    ]
    assert ghost_orders, "unmapped-shop orders must exist to exercise parking"
    # ...and the ghost shop is NOT in the shop list, so shop sync can
    # never create a bar for it.
    async with FakePOSAdapter() as adapter:
        shop_ids = {s.id for s in await adapter.list_shops()}
    assert GHOST_SHOP_ID not in shop_ids
    # Every mapped order's shop IS in the list (sync will create bars).
    for o in orders:
        if o.shop is not None and not isinstance(o.shop, str) and o.shop.id != GHOST_SHOP_ID:
            assert o.shop.id in shop_ids


async def test_identity_fields_and_idempotency_inputs():
    """raw payloads carry a populated user object (the customer_key the
    feature layer depends on); order/line ids are stable so the real
    idempotency keys slesh:<order_id>:<line_id> replay correctly."""
    async with FakePOSAdapter() as adapter:
        first = await _collect(adapter, order_type=None)
    async with FakePOSAdapter() as adapter:
        second = await _collect(adapter, order_type=None)

    # Deterministic: same window → identical stream (ids, lines, amounts).
    assert [o.id for o in first] == [o.id for o in second]
    assert [
        (ln.id, ln.status, ln.gross_amount) for o in first for ln in o.cart
    ] == [
        (ln.id, ln.status, ln.gross_amount) for o in second for ln in o.cart
    ]

    # user arrives as a BARE string id — the provider's unpopulated wire
    # shape (no populatedField param on the real adapter's list_orders),
    # which is what makes the ingester store it as {'_id': ...} in
    # raw_extras. A populated object here would be dumped by field name
    # ('id') and silently break the customer-features builder.
    with_user = [o for o in first if o.user is not None]
    assert len(with_user) > len(first) * 0.4
    assert all(isinstance(o.user, str) and o.user for o in with_user)

    # Overlapping windows re-serve identical orders — the 60s poll
    # overlap replays through the real idempotency path.
    mid = SINCE + timedelta(hours=2)
    async with FakePOSAdapter() as adapter:
        head = await _collect(adapter, since_ts=SINCE, until_ts=mid, order_type=None)
    head_ids = {o.id for o in head}
    assert head_ids == {o.id for o in first if o.created_at < mid.timestamp() * 1000}


async def test_orders_flow_through_the_real_ingestion_pipeline():
    """The whole point: generated raw payloads run the REAL ingester —
    event_orders upsert, stock lines, parking — with the fiscal identity
    intact on what lands in the database."""
    from sqlalchemy import select

    from app.modules.events.models import Event, EventOrder, EventStatus
    from app.modules.pos.models import PendingShopMapping
    from app.modules.pos.order_ingester import _LookupCache, ingest_order
    from app.modules.products.models import ProductType
    from app.modules.stock_transactions.models import StockTransaction
    from app.modules.stock_transactions.service import StockTransactionService
    from tests.fixtures.alerts.factories import (
        delete_tenant_cascade, make_bar, make_event, make_product, make_tenant,
    )
    from tests.fixtures.alerts.session import TestSessionLocal

    window_start = datetime(2026, 9, 5, 18, 0, tzinfo=LOCAL_TZ)
    window_end = window_start + timedelta(minutes=10)

    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        try:
            event = await make_event(session, tenant.id, status=EventStatus.LIVE)
            async with FakePOSAdapter() as adapter:
                shops = await adapter.list_shops()
                products = await adapter.list_products()
                orders = await _collect(
                    adapter, since_ts=window_start, until_ts=window_end,
                    order_type=None,
                )

            # Seed bars + products exactly as staging will: bars mapped by
            # slesh_negozio_id, products by external_pos_id.
            for shop in shops:
                bar = await make_bar(session, tenant.id, event.id)
                bar.slesh_negozio_id = shop.id
                bar.name = shop.name
            for p in products:
                display_name = p.name.get("it", next(iter(p.name.values())))
                row = await make_product(
                    session, tenant.id, name=display_name,
                    product_type=(
                        ProductType.FOOD
                        if display_name in ("Panino", "Arancina")
                        else ProductType.DRINK
                    ),
                )
                row.external_pos_id = p.id
            await session.flush()

            service = StockTransactionService(session)
            cache = _LookupCache()
            for order in orders:
                await ingest_order(
                    db=session, order=order, event_id=event.id,
                    tenant_id=tenant.id, service=service, cache=cache,
                )
            await session.commit()

            eo_rows = (await session.execute(
                select(EventOrder).where(EventOrder.event_id == event.id)
            )).scalars().all()
            ghost_count = sum(
                1 for o in orders
                if o.shop is not None and not isinstance(o.shop, str)
                and o.shop.id == GHOST_SHOP_ID
            )
            # Ghost-shop orders park instead of landing in event_orders.
            assert len(eo_rows) == len(orders) - ghost_count
            assert len(eo_rows) > 50

            # The verified production identity holds on every stored row.
            for row in eo_rows:
                assert row.subtotal_cents == row.fiscal_gross_cents + row.deposit_cents

            # Stock lines exist (units layer ran).
            st_count = (await session.execute(
                select(StockTransaction).where(StockTransaction.event_id == event.id)
            )).scalars().all()
            assert len(st_count) > 0

            if ghost_count:
                parked = (await session.execute(
                    select(PendingShopMapping).where(
                        PendingShopMapping.event_id == event.id,
                        PendingShopMapping.resolved_at.is_(None),
                    )
                )).scalars().all()
                assert parked and parked[0].slesh_shop_id == GHOST_SHOP_ID
        finally:
            await delete_tenant_cascade(session, tenant.id)


async def test_ingested_identity_satisfies_the_feature_builders_expression():
    """Regression for the Day-5 staging close: 8,084 orders processed,
    ZERO sessions created. The fake emitted user/operator as POPULATED
    objects; the ingester's _as_extras_blob dumps parsed models by FIELD
    NAME ('id'), while the provider actually sends bare Mongo id strings
    — the string branch — which land as {'_id': ...}. The feature
    builder consumes raw_extras->'user'->>'_id' (verified against
    production 22 Aug). This test asserts the CONSUMER'S OWN EXPRESSION
    over rows the REAL ingester stored, then runs the real build_event
    and demands sessions and purchases actually materialize."""
    from datetime import datetime, timedelta

    from sqlalchemy import text

    from app.modules.events.models import EventStatus
    from app.modules.pos.order_ingester import _LookupCache, ingest_order
    from app.modules.products.models import ProductType
    from app.modules.stock_transactions.service import StockTransactionService
    from app.scripts.build_customer_features import build_event
    from tests.fixtures.alerts.factories import (
        delete_tenant_cascade, make_bar, make_event, make_product, make_tenant,
    )
    from tests.fixtures.alerts.session import TestSessionLocal

    window_start = datetime(2026, 9, 5, 18, 0, tzinfo=LOCAL_TZ)

    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        tenant_id = tenant.id
        try:
            event = await make_event(session, tenant_id, status=EventStatus.COMPLETED)
            event_id = event.id
            async with FakePOSAdapter() as adapter:
                shops = await adapter.list_shops()
                products = await adapter.list_products()
                for shop in shops:
                    bar = await make_bar(session, tenant_id, event_id)
                    bar.slesh_negozio_id = shop.id
                for p in products:
                    row = await make_product(
                        session, tenant_id, name=p.name["it"],
                        product_type=(
                            ProductType.FOOD if p.name["it"] in ("Panino", "Arancina")
                            else ProductType.DRINK
                        ),
                    )
                    row.external_pos_id = p.id
                await session.flush()

                service = StockTransactionService(session)
                cache = _LookupCache()
                async for order in adapter.list_orders(
                    window_start, window_start + timedelta(minutes=10),
                    order_type=None,
                ):
                    await ingest_order(
                        db=session, order=order, event_id=event_id,
                        tenant_id=tenant_id, service=service, cache=cache,
                    )
            await session.commit()

            # THE consumer's expression, verbatim — not a shape we assert
            # is correct, the exact SQL build_customer_features runs.
            identified = (await session.execute(text("""
                SELECT count(*) FROM event_orders
                WHERE tenant_id = :tid AND event_id = :eid
                  AND confirmed_line_count > 0
                  AND raw_extras->'user'->>'_id' IS NOT NULL
            """), {"tid": str(tenant_id), "eid": str(event_id)})).scalar_one()
            total = (await session.execute(text("""
                SELECT count(*) FROM event_orders
                WHERE tenant_id = :tid AND event_id = :eid
                  AND confirmed_line_count > 0
            """), {"tid": str(tenant_id), "eid": str(event_id)})).scalar_one()
            assert total > 20
            assert identified > total * 0.5, (
                f"only {identified}/{total} orders satisfy "
                "raw_extras->'user'->>'_id' — the identity key the feature "
                "builder reads is not what the ingester stored"
            )

            # And the real consumer must actually build from it.
            report = await build_event(tenant_id=tenant_id, event_id=event_id)
            assert report.sessions_created > 0, (
                "populate_customer_features' core created zero sessions "
                "from ingested fake orders — the Day-5 silent failure"
            )
            assert report.purchases_created > 0
            assert report.distinct_customers == report.sessions_created
        finally:
            await delete_tenant_cascade(session, tenant_id)
