"""Tests for the Phase 2 feature-layer build script.

Two layers, matching the script's own split:
- Pure-function unit tests (bucket_category, is_deposit_product,
  normalize_product_name, percentile_stats, build_session_row) — no DB,
  no network.
- Real-Postgres integration tests proving the actual SQL
  (event_orders as the session's primary source; stock_transactions ->
  event_orders -> products as the line join) matches what the
  completeness audit already validated, including the zero-line-order
  case (a real order with a real customer_key and zero matching
  stock_transactions rows) and the sanity gate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.customer_analytics.models import CustomerPurchase, CustomerSession
from app.modules.events.models import EventOrder
from app.modules.products.models import ProductType
from app.modules.stock_transactions.models import TransactionSource
from app.scripts.build_customer_features import (
    _chunked,
    build_event,
    build_session_row,
    bucket_category,
    fetch_identified_orders,
    fetch_purchase_lines,
    fetch_total_deposit_cents,
    fetch_zero_line_order_stats,
    is_deposit_product,
    normalize_product_name,
    percentile_stats,
)
from tests.fixtures.alerts.factories import (
    delete_tenant_cascade,
    make_bar,
    make_event,
    make_product,
    make_stock_transaction,
    make_tenant,
)
from tests.fixtures.alerts.session import TestSessionLocal

# ─── _chunked ────────────────────────────────────────────────────────────
# asyncpg caps bind parameters at 32,767; a one-shot bulk insert of a
# full event's rows blew past that in production (Sundance 14, ~6,950
# purchase rows). Batching fixed it — this is the regression test.

def test_chunked_splits_into_expected_batch_sizes():
    batches = list(_chunked(list(range(2500)), 1000))
    assert [len(b) for b in batches] == [1000, 1000, 500]


def test_chunked_empty_list():
    assert list(_chunked([], 1000)) == []


def test_chunked_smaller_than_batch_size():
    assert list(_chunked([1, 2, 3], 1000)) == [[1, 2, 3]]


# ─── bucket_category ────────────────────────────────────────────────────

def test_bucket_category_food():
    assert bucket_category("food", None, "Cheesburger") == "food"


def test_bucket_category_spritz_by_name_regardless_of_catalog_category():
    assert bucket_category("drink", "basic_cocktail", "SPRITZ ARANCIO") == "spritz"
    assert bucket_category("drink", "basic_cocktail", "Spritz Rosso") == "spritz"


def test_bucket_category_spritz_catches_known_misspelling():
    assert bucket_category("drink", "basic_cocktail", "Sprtiz Arancio") == "spritz"


def test_bucket_category_spritz_with_null_category():
    assert bucket_category("drink", None, "Hugo Spritz") == "spritz"


def test_bucket_category_beer():
    assert bucket_category("drink", "beer_draft", "Birra Heineken") == "beer"
    assert bucket_category("drink", "beer_bottle", "Heineken") == "beer"


def test_bucket_category_premium():
    assert bucket_category("drink", "premium_cocktail", "N3 Gin") == "premium"


def test_bucket_category_wine():
    assert bucket_category("drink", "wine_red", "Bottiglia Vino") == "wine"
    assert bucket_category("drink", "wine_sparkling", "Prosecco Calice") == "wine"


def test_bucket_category_cocktail():
    assert bucket_category("drink", "basic_cocktail", "Gin Tonic") == "cocktail"


def test_bucket_category_null_category_falls_to_other():
    assert bucket_category("drink", None, "Bicchiere") == "other"


def test_bucket_category_soft_drink_is_other():
    assert bucket_category("drink", "soft_drink", "Acqua Naturale") == "other"


# ─── is_deposit_product ──────────────────────────────────────────────────

def test_is_deposit_product_known_names():
    assert is_deposit_product("Bicchiere") is True
    assert is_deposit_product("Cauzione Bottiglia") is True
    assert is_deposit_product("Free Bicchiere") is True


def test_is_deposit_product_case_and_whitespace_insensitive():
    assert is_deposit_product("  BICCHIERE  ") is True
    assert is_deposit_product("cauzione   bottiglia") is True


def test_is_deposit_product_real_drinks_are_not_deposits():
    assert is_deposit_product("Gin Tonic") is False
    assert is_deposit_product("Free Drink") is False  # a comped drink, not a cup deposit
    assert is_deposit_product("Hugo Spritz") is False


# ─── normalize_product_name ─────────────────────────────────────────────

def test_normalize_product_name_collapses_whitespace_and_case():
    assert normalize_product_name("  Bottiglia   Vino  ") == "bottiglia vino"
    assert normalize_product_name("BOTTIGLIA VINO") == "bottiglia vino"


def test_normalize_product_name_handles_none():
    assert normalize_product_name(None) == ""


# ─── percentile_stats ────────────────────────────────────────────────────

def test_percentile_stats_empty():
    assert percentile_stats([]) == (0.0, 0.0)


def test_percentile_stats_basic():
    median, p90 = percentile_stats([1, 2, 3, 4, 5, 100])
    assert median == 3.5
    assert p90 > median


# ─── build_session_row ───────────────────────────────────────────────────

def _order(**overrides) -> dict:
    base = dict(
        slesh_order_id="ord-1",
        created_at_slesh=datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc),
        customer_email="jane@example.com",
        user_source="live",
        bar_id=uuid4(),
        fiscal_gross_cents=1000,
    )
    base.update(overrides)
    return base


def _line(**overrides) -> dict:
    base = dict(
        slesh_order_id="ord-1",
        ordered_at=datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc),
        product_id=uuid4(),
        bar_id=uuid4(),
        qty=Decimal("1"),
        price_cents=1000,
        product_name="Gin Tonic",
        product_type="drink",
        product_category="basic_cocktail",
        bucket="cocktail",
        is_deposit=False,
    )
    base.update(overrides)
    return base


def test_build_session_row_totals_come_from_orders_not_lines():
    """total_spend_cents must be sum(fiscal_gross_cents), NOT sum of line
    prices — the 2026-07-29 correction. Use deliberately mismatched
    numbers to prove which source wins."""
    orders = [_order(slesh_order_id="ord-1", fiscal_gross_cents=5000)]
    lines = [_line(slesh_order_id="ord-1", price_cents=1000)]  # would give 1000 if lines won
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1",
                                orders=orders, lines=lines)
    assert result.session["total_spend_cents"] == 5000
    assert result.session["order_count"] == 1


def test_build_session_row_zero_lines_still_produces_full_session():
    """The core Q1 fix: an order with zero matching stock_transactions
    rows must still produce a complete session from event_orders alone."""
    orders = [_order(slesh_order_id="ord-1", fiscal_gross_cents=2000)]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1",
                                orders=orders, lines=[])
    s = result.session
    assert s["order_count"] == 1
    assert s["total_spend_cents"] == 2000
    assert s["avg_order_cents"] == 2000
    assert s["orders_with_lines"] == 0
    assert s["has_full_line_coverage"] is False
    assert s["drink_count"] == 0
    assert s["food_count"] == 0
    assert result.unmapped_products == set()


def test_build_session_row_partial_line_coverage():
    """Two orders, only one has matching lines — orders_with_lines=1,
    order_count=2, has_full_line_coverage=False. Both orders' money
    still counts."""
    orders = [
        _order(slesh_order_id="ord-1", fiscal_gross_cents=1000,
               created_at_slesh=datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc)),
        _order(slesh_order_id="ord-2", fiscal_gross_cents=1500,
               created_at_slesh=datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc)),
    ]
    lines = [_line(slesh_order_id="ord-1")]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1",
                                orders=orders, lines=lines)
    s = result.session
    assert s["order_count"] == 2
    assert s["total_spend_cents"] == 2500
    assert s["orders_with_lines"] == 1
    assert s["has_full_line_coverage"] is False
    assert s["drink_count"] == 1


def test_build_session_row_full_line_coverage_true_when_all_orders_have_lines():
    orders = [_order(slesh_order_id="ord-1", fiscal_gross_cents=1000)]
    lines = [_line(slesh_order_id="ord-1")]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1",
                                orders=orders, lines=lines)
    assert result.session["has_full_line_coverage"] is True
    assert result.session["orders_with_lines"] == 1


def test_build_session_row_deposit_lines_excluded_from_drink_and_category_counts():
    orders = [_order(slesh_order_id="ord-1", fiscal_gross_cents=1200)]
    lines = [
        _line(product_name="Gin Tonic", bucket="cocktail", is_deposit=False),
        _line(product_name="Bicchiere", bucket="other", is_deposit=True, product_category=None),
    ]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1",
                                orders=orders, lines=lines)
    s = result.session
    assert s["drink_count"] == 1  # Bicchiere excluded
    assert s["cocktail_count"] == 1
    assert s["other_count"] == 0  # would be 1 if the deposit line leaked in
    # deposit lines are not reported as "unmapped" even though category IS NULL
    assert result.unmapped_products == set()


def test_build_session_row_placeholder_email_is_not_registered():
    orders = [_order(customer_email="abc123@slesh.it")]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1",
                                orders=orders, lines=[])
    assert result.session["is_registered"] is False
    assert result.session["email_domain"] == "slesh.it"


def test_build_session_row_no_email_anywhere_is_unknown_not_guest():
    orders = [_order(customer_email=None)]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1",
                                orders=orders, lines=[])
    assert result.session["is_registered"] is None
    assert result.session["email_domain"] is None


def test_build_session_row_any_backfill_order_marks_whole_session_backfill():
    orders = [
        _order(slesh_order_id="ord-1", user_source="live"),
        _order(slesh_order_id="ord-2", user_source="backfill"),
    ]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1",
                                orders=orders, lines=[])
    assert result.session["user_source"] == "backfill"


def test_build_session_row_distinct_bars_and_first_bar_id():
    bar_a, bar_b = uuid4(), uuid4()
    orders = [
        _order(slesh_order_id="ord-1", bar_id=bar_a, created_at_slesh=datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc)),
        _order(slesh_order_id="ord-2", bar_id=bar_b, created_at_slesh=datetime(2026, 7, 19, 15, 0, tzinfo=timezone.utc)),
    ]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1",
                                orders=orders, lines=[])
    assert result.session["distinct_bars"] == 2
    assert result.session["first_bar_id"] == bar_a


def test_build_session_row_reports_unmapped_products_excluding_deposits_and_food():
    orders = [_order()]
    lines = [
        _line(product_name="Bicchiere", product_category=None, bucket="other", is_deposit=True),
        _line(product_name="No.3 MULE", product_category=None, bucket="other", is_deposit=False),
        _line(product_name="Cheesburger", product_type="food", product_category=None, bucket="food", is_deposit=False),
    ]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1",
                                orders=orders, lines=lines)
    assert len(result.unmapped_products) == 1
    name, _ = next(iter(result.unmapped_products))
    assert name == "no.3 mule"


# ─────────────────────────────────────────────────────────────────────
# Integration — real Postgres
# ─────────────────────────────────────────────────────────────────────
async def _make_identified_order(
    session, *, tenant_id, event_id, slesh_order_id, user_id, customer_email=None,
    fiscal_gross_cents=1000, created_at_slesh=None,
):
    order = EventOrder(
        tenant_id=tenant_id,
        event_id=event_id,
        slesh_order_id=slesh_order_id,
        order_type="experience",
        cart_line_count=1,
        confirmed_line_count=1,
        refunded_line_count=0,
        raw_extras={"user": {"_id": user_id}},
        customer_email=customer_email,
        fiscal_gross_cents=fiscal_gross_cents,
        created_at_slesh=created_at_slesh or datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc),
    )
    session.add(order)
    await session.flush()
    return order


@pytest.mark.asyncio
async def test_fetch_identified_orders_and_zero_line_stats():
    """An order with a real customer_key and NO matching stock_transaction
    row must appear in fetch_identified_orders and count toward
    fetch_zero_line_order_stats — the core Q1 scenario, on real Postgres."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)
        bar = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id, product_type=ProductType.DRINK)

        with_lines = await _make_identified_order(
            session, tenant_id=tenant.id, event_id=event.id,
            slesh_order_id="o-1", user_id="user-a", fiscal_gross_cents=1000,
        )
        zero_line = await _make_identified_order(
            session, tenant_id=tenant.id, event_id=event.id,
            slesh_order_id="o-2", user_id="user-b", fiscal_gross_cents=2500,
        )
        await make_stock_transaction(
            session, tenant.id, event.id, bar.id, product.id,
            source=TransactionSource.SLESH_POS,
            idempotency_key=f"slesh:{with_lines.slesh_order_id}:line-1",
        )
        await session.commit()

        orders = await fetch_identified_orders(session, tenant.id, event.id)
        assert {o["slesh_order_id"] for o in orders} == {"o-1", "o-2"}

        zero_count, zero_revenue = await fetch_zero_line_order_stats(session, tenant.id, event.id)
        assert zero_count == 1
        assert zero_revenue == 2500
        # Regression: asyncpg returns sum()/count() as Decimal; a bare
        # `100.0 * Decimal` crashed the production report. Must be plain int.
        assert type(zero_count) is int
        assert type(zero_revenue) is int

        lines = await fetch_purchase_lines(session, tenant.id, event.id)
        assert {ln["slesh_order_id"] for ln in lines} == {"o-1"}

        await delete_tenant_cascade(session, tenant.id)
        await session.commit()


@pytest.mark.asyncio
async def test_fetch_total_deposit_cents_returns_plain_int():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)
        order = await _make_identified_order(
            session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-1", user_id="user-a",
        )
        order.deposit_cents = 1500
        await session.commit()

        total = await fetch_total_deposit_cents(session, tenant.id, event.id)
        assert total == 1500
        assert type(total) is int

        await delete_tenant_cascade(session, tenant.id)
        await session.commit()


@pytest.mark.asyncio
async def test_fetch_purchase_lines_excludes_cascade_child_rows():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)
        bar = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id, product_type=ProductType.DRINK)

        order = await _make_identified_order(
            session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-1", user_id="user-a",
        )
        await make_stock_transaction(
            session, tenant.id, event.id, bar.id, product.id,
            source=TransactionSource.SLESH_POS, idempotency_key=f"slesh:{order.slesh_order_id}:line-1",
        )
        await make_stock_transaction(
            session, tenant.id, event.id, bar.id, product.id,
            source=TransactionSource.SLESH_POS, idempotency_key=None,
        )
        await session.commit()

        lines = await fetch_purchase_lines(session, tenant.id, event.id)
        assert len(lines) == 1

        await delete_tenant_cascade(session, tenant.id)
        await session.commit()


@pytest.mark.asyncio
async def test_build_event_zero_line_order_still_creates_session():
    """End-to-end: an identified order with no stock_transactions rows at
    all must still produce a session and pass the sanity gate — this IS
    the anchor-holds-by-construction guarantee."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)

        await _make_identified_order(
            session, tenant_id=tenant.id, event_id=event.id,
            slesh_order_id="o-1", user_id="user-a", fiscal_gross_cents=3000,
        )
        await session.commit()

    report = await build_event(
        tenant_id=tenant.id, event_id=event.id, expected_customers=1, known_revenue_cents=3000,
    )
    assert report.sanity_passed is True
    assert report.sessions_created == 1
    assert report.purchases_created == 0
    assert report.zero_line_orders == 1
    assert report.zero_line_orders_revenue_cents == 3000

    async with TestSessionLocal() as session:
        sessions = (await session.execute(
            select(CustomerSession).where(CustomerSession.event_id == event.id)
        )).scalars().all()
        assert len(sessions) == 1
        assert sessions[0].total_spend_cents == 3000
        assert sessions[0].has_full_line_coverage is False

        await delete_tenant_cascade(session, tenant.id)
        await session.commit()


@pytest.mark.asyncio
async def test_build_event_writes_sessions_and_purchases_end_to_end():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)
        bar = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id, product_type=ProductType.DRINK)

        order = await _make_identified_order(
            session, tenant_id=tenant.id, event_id=event.id,
            slesh_order_id="o-1", user_id="mongo-user-1", customer_email="jane@example.com",
            fiscal_gross_cents=1000,
        )
        await make_stock_transaction(
            session, tenant.id, event.id, bar.id, product.id,
            source=TransactionSource.SLESH_POS, idempotency_key=f"slesh:{order.slesh_order_id}:line-1",
        )
        await session.commit()

    report = await build_event(
        tenant_id=tenant.id, event_id=event.id, expected_customers=1, known_revenue_cents=1000,
    )
    assert report.sanity_passed is True
    assert report.sessions_created == 1
    assert report.purchases_created == 1

    async with TestSessionLocal() as session:
        sessions = (await session.execute(
            select(CustomerSession).where(CustomerSession.event_id == event.id)
        )).scalars().all()
        purchases = (await session.execute(
            select(CustomerPurchase).where(CustomerPurchase.event_id == event.id)
        )).scalars().all()
        assert len(sessions) == 1
        assert len(purchases) == 1
        assert sessions[0].customer_key == "mongo-user-1"
        assert sessions[0].has_full_line_coverage is True

        await delete_tenant_cascade(session, tenant.id)
        await session.commit()


@pytest.mark.asyncio
async def test_build_event_sanity_gate_blocks_write_on_mismatch():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)

        await _make_identified_order(
            session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-1", user_id="mongo-user-1",
        )
        await session.commit()

    report = await build_event(
        tenant_id=tenant.id, event_id=event.id, expected_customers=999, known_revenue_cents=0,
    )
    assert report.sanity_passed is False

    async with TestSessionLocal() as session:
        sessions = (await session.execute(
            select(CustomerSession).where(CustomerSession.event_id == event.id)
        )).scalars().all()
        assert sessions == [], "sanity gate failed but rows were written anyway"

        await delete_tenant_cascade(session, tenant.id)
        await session.commit()
