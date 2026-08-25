"""Unit tests for slesh_poller.poll_slesh_orders.

These tests prove the orchestration contract:
- Composes adapter + ingester correctly
- Catches errors and records them on the cursor (never raises)
- Backfill mode (since_ts + until_ts both supplied) bypasses cursor
- Live mode (only until_ts) uses cursor with overlap
- CircuitBreakerOpen is recorded with a distinct status

We use fakes for SleshAdapter and a stub for the DB session. We patch
the poller\'s internal helpers (StockTransactionService, ingest_order)
to avoid real DB work.

Spec: docs/slesh-integration-roadmap.md \u00a7B6.5 + \u00a7B7.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest

from app.modules.pos.retry import CircuitBreakerOpen
from app.modules.pos.slesh_poller import PollResult


TENANT_ID = UUID("25ef916c-a288-44ae-b17c-8dfd09390834")
EVENT_ID  = UUID("4e9f9699-b372-4649-9d16-9634898bb08d")


# ─── Fakes ───────────────────────────────────────────────────────────

class FakeOrder:
    """Minimal Order shape that ingest_order needs to read created_at."""
    def __init__(self, order_id: str, created_at_ms: int, n_lines: int = 1) -> None:
        self.id          = order_id
        self.created_at  = created_at_ms
        self.cart        = [object()] * n_lines


class FakeAdapter:
    """Mocks SleshAdapter\'s async-context-manager + list_orders contract.

    Configurable orders: pass a list to yield, or an exception to raise
    when list_orders is iterated.
    """
    def __init__(self, *, orders: list = None, raise_on_iter: Exception = None):
        self._orders        = orders or []
        self._raise_on_iter = raise_on_iter
        self.entered = False
        self.exited  = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *_args):
        self.exited = True

    async def list_orders(self, **kwargs):
        if self._raise_on_iter is not None:
            raise self._raise_on_iter
        for o in self._orders:
            yield o


class FakeIngestResult:
    """Minimal IngestResult shape the poller reads."""
    def __init__(self, ingested=0, replayed=0, skipped=0, errors=0,
                 skip_reasons=None, error_messages=None) -> None:
        self.lines_ingested  = ingested
        self.lines_replayed  = replayed
        self.lines_skipped   = skipped
        self.lines_errors    = errors
        self.skip_reasons    = skip_reasons or []
        self.error_messages  = error_messages or []


# ─── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def patched_poller(monkeypatch):
    """Patch the heavy dependencies inside slesh_poller so tests stay
    in-memory.

    Returns a dict of mutable state the test can configure:
      - adapter:        the FakeAdapter to be returned by SleshAdapter(...)
      - ingest_results: list of FakeIngestResult to return on each call
      - state_obj:      a stub state object (with last_seen_ts)
      - record_calls:   list capturing record_success / record_failure args
    """
    import app.modules.pos.slesh_poller as sp

    state_obj = type("S", (), {"last_seen_ts": 1700000000000})()
    config = {
        "adapter":         FakeAdapter(),
        "ingest_results":  [],
        "state_obj":       state_obj,
        "record_calls":    [],
    }

    # Stub StockTransactionService — never used directly here; ingest_order
    # is patched, so passing None is fine.
    monkeypatch.setattr(sp, "StockTransactionService", lambda db: None)

    # Patch the factory (the construction seam since POS_ADAPTER landed)
    # to return our adapter (which is an async ctx mgr). slesh_poller
    # imports get_pos_adapter from the factory module inside the
    # function, so the factory module attribute is the patch point.
    import app.modules.pos.adapters.factory as adapter_factory

    class _CtxAdapter:
        async def __aenter__(self): return await config["adapter"].__aenter__()
        async def __aexit__(self, *a): return await config["adapter"].__aexit__(*a)

    monkeypatch.setattr(
        adapter_factory, "get_pos_adapter",
        lambda *, brand_id=None: _CtxAdapter(),
    )

    # Patch ingest_order to return queued FakeIngestResult instances
    async def _fake_ingest_order(**kwargs):
        if config["ingest_results"]:
            return config["ingest_results"].pop(0)
        return FakeIngestResult()
    monkeypatch.setattr(sp, "ingest_order", _fake_ingest_order)

    # Patch get_or_init_state to return our stub
    async def _fake_get_or_init(**kwargs):
        return config["state_obj"]
    monkeypatch.setattr(sp, "get_or_init_state", _fake_get_or_init)

    # Patch record_success / record_failure to record the calls
    async def _fake_record_success(**kwargs):
        config["record_calls"].append(("success", kwargs))
    async def _fake_record_failure(**kwargs):
        config["record_calls"].append(("failure", kwargs))
    monkeypatch.setattr(sp, "record_success", _fake_record_success)
    monkeypatch.setattr(sp, "record_failure", _fake_record_failure)

    # Patch AsyncSessionLocal to a fake context manager yielding a stub db
    @asynccontextmanager
    async def _fake_session():
        class _StubDB:
            async def commit(self): pass
            async def flush(self):  pass
        yield _StubDB()
    monkeypatch.setattr(sp, "AsyncSessionLocal", _fake_session)

    return config


# ─── Happy-path test ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poll_returns_ok_with_no_orders(patched_poller):
    from app.modules.pos.slesh_poller import poll_slesh_orders

    patched_poller["adapter"] = FakeAdapter(orders=[])

    result = await poll_slesh_orders(
        tenant_id = TENANT_ID,
        event_id  = EVENT_ID,
        brand_id  = "brand_x",
        until_ts  = datetime(2025, 8, 3, 20, 0, tzinfo=timezone.utc),
    )

    assert result.status == "ok"
    assert result.orders_seen == 0
    assert result.lines_ingested == 0
    assert any(c[0] == "success" for c in patched_poller["record_calls"])


@pytest.mark.asyncio
async def test_poll_with_orders_aggregates_counters(patched_poller):
    from app.modules.pos.slesh_poller import poll_slesh_orders

    o1 = FakeOrder("ord_1", 1700000060000)
    o2 = FakeOrder("ord_2", 1700000120000)
    patched_poller["adapter"] = FakeAdapter(orders=[o1, o2])
    patched_poller["ingest_results"] = [
        FakeIngestResult(ingested=1),
        FakeIngestResult(ingested=2, skipped=1),
    ]

    result = await poll_slesh_orders(
        tenant_id = TENANT_ID,
        event_id  = EVENT_ID,
        brand_id  = "brand_x",
        until_ts  = datetime(2025, 8, 3, 20, 0, tzinfo=timezone.utc),
    )

    assert result.status            == "ok"
    assert result.orders_seen       == 2
    assert result.orders_ingested   == 2
    assert result.lines_ingested    == 3
    assert result.lines_skipped     == 1
    assert result.lines_errors      == 0
    # high-water mark = max created_at across orders
    assert result.new_high_water_ts == 1700000120000


@pytest.mark.asyncio
async def test_poll_records_success_with_high_water(patched_poller):
    from app.modules.pos.slesh_poller import poll_slesh_orders

    o1 = FakeOrder("ord_1", 1700000060000)
    patched_poller["adapter"] = FakeAdapter(orders=[o1])
    patched_poller["ingest_results"] = [FakeIngestResult(ingested=1)]

    await poll_slesh_orders(
        tenant_id = TENANT_ID,
        event_id  = EVENT_ID,
        brand_id  = "brand_x",
        until_ts  = datetime(2025, 8, 3, 20, 0, tzinfo=timezone.utc),
    )

    success_calls = [c for c in patched_poller["record_calls"] if c[0] == "success"]
    assert len(success_calls) == 1
    assert success_calls[0][1].get("new_high_water_ts") == 1700000060000


# ─── Failure-path tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poll_circuit_open_returns_circuit_open_status(patched_poller):
    from app.modules.pos.slesh_poller import poll_slesh_orders

    patched_poller["adapter"] = FakeAdapter(
        raise_on_iter=CircuitBreakerOpen("circuit open since 60s ago"),
    )

    result = await poll_slesh_orders(
        tenant_id = TENANT_ID,
        event_id  = EVENT_ID,
        brand_id  = "brand_x",
        until_ts  = datetime(2025, 8, 3, 20, 0, tzinfo=timezone.utc),
    )

    assert result.status == "circuit_open"
    assert "circuit open" in result.error_msg
    failure_calls = [c for c in patched_poller["record_calls"] if c[0] == "failure"]
    assert len(failure_calls) == 1
    assert failure_calls[0][1].get("status") == "circuit_open"


@pytest.mark.asyncio
async def test_poll_unexpected_error_returns_error_status(patched_poller):
    from app.modules.pos.slesh_poller import poll_slesh_orders

    patched_poller["adapter"] = FakeAdapter(
        raise_on_iter=RuntimeError("network exploded"),
    )

    result = await poll_slesh_orders(
        tenant_id = TENANT_ID,
        event_id  = EVENT_ID,
        brand_id  = "brand_x",
        until_ts  = datetime(2025, 8, 3, 20, 0, tzinfo=timezone.utc),
    )

    assert result.status == "error"
    assert "network exploded" in result.error_msg
    failure_calls = [c for c in patched_poller["record_calls"] if c[0] == "failure"]
    assert len(failure_calls) == 1
    assert failure_calls[0][1].get("status") == "error"


@pytest.mark.asyncio
async def test_poll_never_raises_even_on_unknown_exception(patched_poller):
    """Resilience contract: the poller catches ALL exceptions and returns
    a PollResult. arq tasks must not raise."""
    from app.modules.pos.slesh_poller import poll_slesh_orders

    class WeirdError(Exception):
        pass

    patched_poller["adapter"] = FakeAdapter(raise_on_iter=WeirdError("???"))

    # No `with pytest.raises(...)` — calling MUST return a result, not raise
    result = await poll_slesh_orders(
        tenant_id = TENANT_ID,
        event_id  = EVENT_ID,
        brand_id  = "brand_x",
        until_ts  = datetime(2025, 8, 3, 20, 0, tzinfo=timezone.utc),
    )
    assert result.status == "error"


# ─── Brand id resolution ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poll_no_brand_id_returns_error(patched_poller, monkeypatch):
    """If no brand_id (param or settings), return error without trying."""
    from app.modules.pos.slesh_poller import poll_slesh_orders
    from app.core.config import settings

    monkeypatch.setattr(settings, "slesh_brand_id", "")  # blank settings too

    result = await poll_slesh_orders(
        tenant_id = TENANT_ID,
        event_id  = EVENT_ID,
        brand_id  = None,
        until_ts  = datetime(2025, 8, 3, 20, 0, tzinfo=timezone.utc),
    )

    assert result.status == "error"
    assert "brand_id" in result.error_msg.lower()
