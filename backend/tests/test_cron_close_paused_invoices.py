"""Tests for cron_close_paused_invoices' session isolation (F-03).

Regression coverage for the bug where the cron shared ONE session across
every eligible invoice in a tick and its catch-all `except Exception` never
rolled back. A genuine DB-level failure closing one invoice left that shared
session's transaction aborted; every SUBSEQUENT invoice in the same tick then
failed too — on its very first query — misattributed as N separate
"failed to close" invoices instead of 1 root cause + N cascades.

Same SAVEPOINT + patched-session-factory pattern as
test_event_auto_transitions.py (F-02's own regression test), applied to
app.workers.tasks.async_session_factory this time.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.warehouse.invoice_service as invoice_service_module
import app.workers.tasks as tasks_module
from app.modules.warehouse.models import DeliveryInvoice
from app.workers.tasks import cron_close_paused_invoices
from tests.fixtures.alerts.factories import make_tenant

pytestmark = pytest.mark.asyncio


@pytest.fixture
def patched_isolated_session_factory(db_session: AsyncSession, monkeypatch):
    """Each async_session_factory() call returns a genuinely separate
    AsyncSession bound to db_session's connection (SAVEPOINT-scoped, so
    everything still rolls back at test teardown) but with its own identity
    map — the same pattern test_event_auto_transitions.py uses to exercise
    F-02 meaningfully. Needed here for the identical reason: a shared,
    literal db_session couldn't distinguish "fixed" from "still shares one
    session," since either way a rollback on that single object would
    affect everything.
    """
    NestedSession = async_sessionmaker(
        bind=db_session._test_connection, expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    opened: list[AsyncSession] = []

    class _FreshSessionWrapper:
        async def __aenter__(self):
            session = NestedSession()
            opened.append(session)
            return session
        async def __aexit__(self, *args):
            await opened[-1].close()
            return None

    monkeypatch.setattr(
        tasks_module, "async_session_factory",
        lambda: _FreshSessionWrapper(),
    )
    return db_session


async def _make_invoice(db_session, tenant_id, *, scan_started_at) -> DeliveryInvoice:
    inv = DeliveryInvoice(
        tenant_id=tenant_id,
        supplier_name="Test Supplier",
        expected_arrival_date=date.today(),
        status="PAUSED",
        scan_started_at=scan_started_at,
    )
    db_session.add(inv)
    await db_session.flush()
    return inv


async def test_one_invoice_failure_does_not_poison_the_next(
    db_session: AsyncSession, patched_isolated_session_factory, monkeypatch,
):
    """A genuine DB-level failure closing the FIRST (oldest-paused, so
    processed first per the cron's ORDER BY) invoice must not prevent the
    SECOND, unrelated invoice from closing successfully in the same tick."""
    now = datetime.now(timezone.utc)
    tenant = await make_tenant(db_session)
    bad = await _make_invoice(db_session, tenant.id, scan_started_at=now - timedelta(hours=72))
    good = await _make_invoice(db_session, tenant.id, scan_started_at=now - timedelta(hours=49))

    async def _fake_close_scan(self, tenant_id, invoice_id, *, closed_by=None):
        if invoice_id == bad.id:
            # A genuine DB-level error (not just a Python exception) —
            # this is what actually aborts the underlying transaction,
            # the real mechanism behind the cascade bug.
            await self.db.execute(text("SELECT 1/0"))
            return None  # unreachable
        result = await self.db.execute(
            select(DeliveryInvoice).where(DeliveryInvoice.id == invoice_id)
        )
        inv = result.scalar_one()
        inv.status = "VERIFIED"
        await self.db.flush()
        await self.db.commit()
        return inv, None

    monkeypatch.setattr(invoice_service_module.InvoiceService, "close_scan", _fake_close_scan)

    result = await cron_close_paused_invoices(ctx={})

    assert result["eligible"] == 2
    assert result["closed"] == 1
    assert result["failed"] == 1

    await db_session.refresh(bad)
    await db_session.refresh(good)
    assert bad.status == "PAUSED"     # failed to close, unchanged
    assert good.status == "VERIFIED"  # closed successfully despite bad's failure
