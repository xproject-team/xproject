"""Tests for the Phase 2 feature-layer build script.

Two layers, matching the script's own split:
- Pure-function unit tests (bucket_category, normalize_product_name,
  percentile_stats, build_session_row) — no DB, no network.
- One real-Postgres integration test proving the actual SQL join
  (stock_transactions -> event_orders via source_idempotency_key ->
  products) matches what the identity audit already validated, and that
  the sanity gate genuinely blocks a write when it should.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.customer_analytics.models import CustomerPurchase, CustomerSession
from app.modules.events.models import EventOrder
from app.modules.products.models import ProductType
from app.modules.stock_transactions.models import TransactionSource
from app.scripts.build_customer_features import (
    build_event,
    build_session_row,
    bucket_category,
    fetch_purchase_lines,
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


# ─── bucket_category ────────────────────────────────────────────────────

def test_bucket_category_food():
    assert bucket_category("food", None, "Cheesburger") == "food"


def test_bucket_category_spritz_by_name_regardless_of_catalog_category():
    """Spritz has no dedicated catalog category — it's always filed under
    basic_cocktail — so name must win over category."""
    assert bucket_category("drink", "basic_cocktail", "SPRITZ ARANCIO") == "spritz"
    assert bucket_category("drink", "basic_cocktail", "Spritz Rosso") == "spritz"


def test_bucket_category_spritz_catches_known_misspelling():
    assert bucket_category("drink", "basic_cocktail", "Sprtiz Arancio") == "spritz"


def test_bucket_category_spritz_with_null_category():
    """Hugo Spritz has category=NULL in the real catalog — must still
    bucket as spritz, not fall through to 'other'."""
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
    """Bicchiere (a cup/glass charge) has category=NULL in the real
    catalog and isn't spritz-named — must land in 'other', not crash."""
    assert bucket_category("drink", None, "Bicchiere") == "other"


def test_bucket_category_soft_drink_is_other():
    assert bucket_category("drink", "soft_drink", "Acqua Naturale") == "other"


# ─── normalize_product_name ─────────────────────────────────────────────

def test_normalize_product_name_collapses_whitespace_and_case():
    assert normalize_product_name("  Bottiglia   Vino  ") == "bottiglia vino"
    assert normalize_product_name("BOTTIGLIA VINO") == "bottiglia vino"
    assert normalize_product_name("Bottiglia Vino") == "bottiglia vino"


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

def _line(**overrides) -> dict:
    base = dict(
        slesh_order_id="ord-1",
        ordered_at=datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc),
        customer_email="jane@example.com",
        user_source="live",
        product_id=uuid4(),
        bar_id=uuid4(),
        qty=Decimal("1"),
        price_cents=1000,
        product_name="Gin Tonic",
        product_type="drink",
        product_category="basic_cocktail",
        bucket="cocktail",
    )
    base.update(overrides)
    return base


def test_build_session_row_basic_aggregation():
    lines = [
        _line(slesh_order_id="ord-1", price_cents=1000, ordered_at=datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc)),
        _line(slesh_order_id="ord-2", price_cents=700, product_name="Heineken", bucket="beer",
              ordered_at=datetime(2026, 7, 19, 18, 30, tzinfo=timezone.utc)),
    ]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1", lines=lines)
    s = result.session

    assert s["order_count"] == 2
    assert s["total_spend_cents"] == 1700
    assert s["avg_order_cents"] == 850
    assert s["first_order_at"] == datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc)
    assert s["last_order_at"] == datetime(2026, 7, 19, 18, 30, tzinfo=timezone.utc)
    assert s["session_minutes"] == 270.0  # 4.5 hours
    assert s["drink_count"] == 2
    assert s["food_count"] == 0
    assert s["cocktail_count"] == 1
    assert s["beer_count"] == 1
    assert s["is_registered"] is True
    assert s["email_domain"] == "example.com"
    assert s["user_source"] == "live"


def test_build_session_row_placeholder_email_is_not_registered():
    lines = [_line(customer_email="abc123@slesh.it")]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1", lines=lines)
    assert result.session["is_registered"] is False
    assert result.session["email_domain"] == "slesh.it"


def test_build_session_row_no_email_anywhere_is_unknown_not_guest():
    lines = [_line(customer_email=None)]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1", lines=lines)
    assert result.session["is_registered"] is None
    assert result.session["email_domain"] is None


def test_build_session_row_any_backfill_line_marks_whole_session_backfill():
    lines = [
        _line(user_source="live"),
        _line(slesh_order_id="ord-2", user_source="backfill"),
    ]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1", lines=lines)
    assert result.session["user_source"] == "backfill"


def test_build_session_row_multiple_lines_same_order_counted_once():
    """Two cart lines on the SAME order must count as order_count=1."""
    lines = [
        _line(slesh_order_id="ord-1", price_cents=1000),
        _line(slesh_order_id="ord-1", price_cents=1200, product_name="Negroni"),
    ]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1", lines=lines)
    assert result.session["order_count"] == 1
    assert result.session["total_spend_cents"] == 2200
    assert result.session["avg_order_cents"] == 2200


def test_build_session_row_distinct_bars_and_first_bar_id():
    bar_a, bar_b = uuid4(), uuid4()
    lines = [
        _line(bar_id=bar_a, ordered_at=datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc)),
        _line(slesh_order_id="ord-2", bar_id=bar_b, ordered_at=datetime(2026, 7, 19, 15, 0, tzinfo=timezone.utc)),
    ]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1", lines=lines)
    assert result.session["distinct_bars"] == 2
    assert result.session["first_bar_id"] == bar_a


def test_build_session_row_reports_unmapped_products():
    lines = [
        _line(product_name="Bicchiere", product_category=None, bucket="other"),
        _line(slesh_order_id="ord-2", product_name="Gin Tonic", product_category="basic_cocktail", bucket="cocktail"),
    ]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1", lines=lines)
    assert len(result.unmapped_products) == 1
    name, pid = next(iter(result.unmapped_products))
    assert name == "bicchiere"


def test_build_session_row_food_lines_excluded_from_category_buckets():
    lines = [
        _line(product_type="food", product_name="Cheesburger", bucket="food", product_category=None),
    ]
    result = build_session_row(tenant_id=uuid4(), event_id=uuid4(), customer_key="user-1", lines=lines)
    s = result.session
    assert s["food_count"] == 1
    assert s["drink_count"] == 0
    assert sum(s[c + "_count"] for c in ("beer", "cocktail", "spritz", "wine", "premium", "other")) == 0
    # food's NULL category must NOT be reported as unmapped — food is
    # never categorized by design, that's not a catalog gap.
    assert result.unmapped_products == set()


# ─────────────────────────────────────────────────────────────────────
# Integration — real Postgres, proves the actual SQL join
# ─────────────────────────────────────────────────────────────────────
async def _make_identified_order(
    session, *, tenant_id, event_id, slesh_order_id, user_id, customer_email=None,
    user_source=None, created_at_slesh=None,
):
    raw_extras = {"user": {"_id": user_id}}
    if user_source:
        raw_extras["user_source"] = user_source
    order = EventOrder(
        tenant_id=tenant_id,
        event_id=event_id,
        slesh_order_id=slesh_order_id,
        order_type="experience",
        cart_line_count=1,
        confirmed_line_count=1,
        refunded_line_count=0,
        raw_extras=raw_extras,
        customer_email=customer_email,
        created_at_slesh=created_at_slesh or datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc),
    )
    session.add(order)
    await session.flush()
    return order


async def _make_unidentified_order(session, *, tenant_id, event_id, slesh_order_id):
    order = EventOrder(
        tenant_id=tenant_id,
        event_id=event_id,
        slesh_order_id=slesh_order_id,
        order_type="experience",
        cart_line_count=1,
        confirmed_line_count=1,
        refunded_line_count=0,
        raw_extras=None,
        created_at_slesh=datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc),
    )
    session.add(order)
    await session.flush()
    return order


@pytest.mark.asyncio
async def test_fetch_purchase_lines_real_join_skips_null_customer_key():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)
        bar = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id, product_type=ProductType.DRINK)

        identified = await _make_identified_order(
            session, tenant_id=tenant.id, event_id=event.id,
            slesh_order_id="o-1", user_id="mongo-user-1", customer_email="jane@example.com",
        )
        unidentified = await _make_unidentified_order(
            session, tenant_id=tenant.id, event_id=event.id, slesh_order_id="o-2",
        )

        await make_stock_transaction(
            session, tenant.id, event.id, bar.id, product.id,
            source=TransactionSource.SLESH_POS,
            idempotency_key=f"slesh:{identified.slesh_order_id}:line-1",
        )
        await make_stock_transaction(
            session, tenant.id, event.id, bar.id, product.id,
            source=TransactionSource.SLESH_POS,
            idempotency_key=f"slesh:{unidentified.slesh_order_id}:line-1",
        )
        await session.commit()

        lines = await fetch_purchase_lines(session, tenant.id, event.id)
        assert len(lines) == 1
        assert lines[0]["customer_key"] == "mongo-user-1"
        assert lines[0]["slesh_order_id"] == "o-1"

        await delete_tenant_cascade(session, tenant.id)
        await session.commit()


@pytest.mark.asyncio
async def test_fetch_purchase_lines_excludes_cascade_child_rows():
    """source_idempotency_key IS NULL must never appear — that's the
    cascade-child exclusion rule."""
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)
        bar = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id, product_type=ProductType.DRINK)

        order = await _make_identified_order(
            session, tenant_id=tenant.id, event_id=event.id,
            slesh_order_id="o-1", user_id="mongo-user-1",
        )
        # Parent — has the key
        await make_stock_transaction(
            session, tenant.id, event.id, bar.id, product.id,
            source=TransactionSource.SLESH_POS, idempotency_key=f"slesh:{order.slesh_order_id}:line-1",
        )
        # "Cascade child" — no key, must be excluded
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
async def test_build_event_writes_sessions_and_purchases_end_to_end():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)
        bar = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id, product_type=ProductType.DRINK)
        product.default_price_cents = 1000

        order = await _make_identified_order(
            session, tenant_id=tenant.id, event_id=event.id,
            slesh_order_id="o-1", user_id="mongo-user-1", customer_email="jane@example.com",
        )
        await make_stock_transaction(
            session, tenant.id, event.id, bar.id, product.id,
            source=TransactionSource.SLESH_POS, idempotency_key=f"slesh:{order.slesh_order_id}:line-1",
        )
        await session.commit()

    report = await build_event(
        tenant_id=tenant.id, event_id=event.id, expected_customers=1, known_revenue_cents=0,
    )
    assert report.sanity_passed is True
    assert report.sessions_created == 1
    assert report.purchases_created == 1
    assert report.distinct_customers == 1

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

        await delete_tenant_cascade(session, tenant.id)
        await session.commit()


@pytest.mark.asyncio
async def test_build_event_sanity_gate_blocks_write_on_mismatch():
    async with TestSessionLocal() as session:
        tenant = await make_tenant(session)
        event = await make_event(session, tenant.id)
        bar = await make_bar(session, tenant.id, event.id)
        product = await make_product(session, tenant.id, product_type=ProductType.DRINK)

        order = await _make_identified_order(
            session, tenant_id=tenant.id, event_id=event.id,
            slesh_order_id="o-1", user_id="mongo-user-1",
        )
        await make_stock_transaction(
            session, tenant.id, event.id, bar.id, product.id,
            source=TransactionSource.SLESH_POS, idempotency_key=f"slesh:{order.slesh_order_id}:line-1",
        )
        await session.commit()

    # Wrong expectation on purpose (real count is 1, not 999)
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
