"""Schema invariant tests (B.4 — pre-Sundance hardening).

These tests lock down the database safety guarantees that protect us at
Sundance. If anyone removes one of these constraints in a future
migration, CI catches it immediately instead of letting Sundance discover
the regression at 9pm with 5,000 guests.

Categories:
1. NOT NULL on every tenant_id column (multi-tenancy guarantee)
2. CHECK constraints on bar_stock and stock_transactions (no negatives,
   no impossible deficits)
3. Unique constraints / partial unique indexes (no duplicate live events,
   no duplicate bar_stock rows, no duplicate emails, etc.)
4. Enum integrity (event_status native enum present with expected values)
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.fixtures.alerts.session import TestSessionLocal


# ── Category 1: tenant_id NOT NULL ────────────────────────────────────────

@pytest.mark.asyncio
async def test_every_tenant_id_column_is_not_null():
    """No table should allow NULL tenant_id — breaks multi-tenancy."""
    async with TestSessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT t.table_name, c.is_nullable
            FROM information_schema.columns c
            JOIN information_schema.tables t ON c.table_name = t.table_name
            WHERE c.column_name = 'tenant_id'
              AND c.is_nullable = 'YES'
              AND t.table_schema = 'public'
        """))).all()
    assert rows == [], f"Tables allowing NULL tenant_id: {rows}"


# ── Category 2: stock CHECK constraints ───────────────────────────────────

@pytest.mark.asyncio
async def test_bar_stock_check_constraints_exist():
    """5 CHECK constraints protect bar_stock from negative/inconsistent qty."""
    async with TestSessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT conname FROM pg_constraint
            WHERE conrelid::regclass::text = 'bar_stock' AND contype = 'c'
            ORDER BY conname
        """))).all()
    names = {r[0] for r in rows}
    required = {
        "bar_stock_allocated_nonneg",
        "bar_stock_current_lte_allocated",
        "bar_stock_current_nonneg",
        "bar_stock_returned_lte_allocated",
        "bar_stock_returned_nonneg",
    }
    missing = required - names
    assert not missing, f"Missing bar_stock CHECK constraints: {missing}"


@pytest.mark.asyncio
async def test_stock_transactions_check_constraints_exist():
    """CHECK constraints on stock_transactions protect against bad data."""
    async with TestSessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT conname FROM pg_constraint
            WHERE conrelid::regclass::text = 'stock_transactions' AND contype = 'c'
            ORDER BY conname
        """))).all()
    names = {r[0] for r in rows}
    required = {
        "stock_transactions_deficit_lte_qty",
        "stock_transactions_deficit_nonneg",
        "stock_transactions_price_nonneg",
        "stock_transactions_qty_positive",
    }
    missing = required - names
    assert not missing, f"Missing stock_transactions CHECK constraints: {missing}"


# ── Category 3: unique indexes (multi-tenancy + lifecycle safety) ─────────

@pytest.mark.asyncio
async def test_critical_unique_indexes_exist():
    """Production-grade safety indexes that prevent catastrophic duplicates."""
    async with TestSessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'public' AND indexdef LIKE '%UNIQUE%'
        """))).all()
    names = {r[0] for r in rows}
    required = {
        "one_live_event_per_tenant",         # max 1 LIVE event per tenant
        "uq_bar_stock_event_bar_product",    # no duplicate stock rows
        "ix_users_email",                    # no duplicate user emails
        "ix_tenants_slug",                   # no duplicate tenant slugs
        "ix_warehouse_inventory_tenant_product",  # one inventory row per product
    }
    missing = required - names
    assert not missing, f"Missing critical unique indexes: {missing}"


# ── Category 4: enum integrity ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_event_status_enum_has_required_values():
    """event_status enum must include all 5 lifecycle states."""
    async with TestSessionLocal() as session:
        rows = (await session.execute(text(
            "SELECT unnest(enum_range(NULL::event_status))::text"
        ))).all()
    values = {r[0] for r in rows}
    required = {"DRAFT", "ACTIVE", "LIVE", "COMPLETED", "CANCELLED"}
    missing = required - values
    assert not missing, f"event_status enum missing values: {missing}"


@pytest.mark.asyncio
async def test_no_orphan_rows_in_critical_tables():
    """Every child row must point to a real parent — catches FK gaps."""
    async with TestSessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT 'bars→events' AS rel, COUNT(*) AS n FROM bars b
              WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.id = b.event_id)
            UNION ALL
            SELECT 'bar_stock→events', COUNT(*) FROM bar_stock bs
              WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.id = bs.event_id)
            UNION ALL
            SELECT 'bar_stock→bars', COUNT(*) FROM bar_stock bs
              WHERE NOT EXISTS (SELECT 1 FROM bars b WHERE b.id = bs.bar_id)
            UNION ALL
            SELECT 'stock_transactions→events', COUNT(*) FROM stock_transactions st
              WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.id = st.event_id)
            UNION ALL
            SELECT 'stock_transactions→bars', COUNT(*) FROM stock_transactions st
              WHERE NOT EXISTS (SELECT 1 FROM bars b WHERE b.id = st.bar_id)
            UNION ALL
            SELECT 'alerts→events', COUNT(*) FROM alerts a
              WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.id = a.event_id)
        """))).all()
    orphans = [r for r in rows if r[1] > 0]
    assert orphans == [], f"Orphan rows found: {orphans}"


@pytest.mark.asyncio
async def test_bars_device_count_not_null():
    """device_count must be NOT NULL — a nullable column 500'd /bars once
    (Phase B w2 added it nullable; w3 fixed it). Lock it forever."""
    async with TestSessionLocal() as session:
        nullable = (await session.execute(text("""
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = 'bars' AND column_name = 'device_count'
        """))).scalar_one()
    assert nullable == "NO", f"bars.device_count is nullable ({nullable})"
