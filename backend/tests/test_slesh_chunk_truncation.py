"""Regression test: Slesh adapter must warn on chunk truncation.

Background: Slesh\'s `from` parameter is broken (verified live 2026-05-25
against production). When a single time-window query has >100 orders,
Slesh returns the first 100 and re-serves the same first 100 on any
subsequent call regardless of `from`. The adapter must:

1. Detect this case (envelope.total > len(docs) AND second-page repeats)
2. Log a clear DATA LOSS warning so the caller knows to narrow the window

This test locks that behaviour. If anyone deletes or weakens the warning
in a future refactor, CI fails immediately.
"""
from __future__ import annotations
import logging
import pytest
import httpx

from app.modules.pos.adapters.slesh import SleshAdapter


def _fake_envelope(total: int, n_docs: int = 100) -> dict:
    """Build a fake Slesh response with `total > n_docs` to simulate
    truncation. Each doc has a stable `_id` so the loop guard fires on
    repeat."""
    return {
        "docs":        [{"_id": f"doc-{i:04d}"} for i in range(n_docs)],
        "from":        1,
        "to":          n_docs,
        "total":       total,
        "hasNextPage": True,
    }


@pytest.mark.asyncio
async def test_warns_on_chunk_truncation(caplog):
    """When Slesh returns 100 docs but total=4515, we must log DATA LOSS."""

    # Mock transport: every call returns the SAME first-100 page.
    fake = _fake_envelope(total=4515, n_docs=100)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fake)

    transport = httpx.MockTransport(handler)

    adapter = SleshAdapter(token="fake", brand_id="fake")
    # adapter._client is the SleshClient wrapper; its inner ._client is the
    # raw httpx.AsyncClient. We swap THAT so _handle_response still runs.
    await adapter.__aenter__()  # initialise the wrapper as production would
    adapter._client._client = httpx.AsyncClient(
        base_url="https://api.slesh.it/api",
        transport=transport,
    )

    caplog.set_level(logging.WARNING, logger="app.modules.pos.adapters.slesh")

    try:
        collected = []
        async for doc in adapter._iter_paginated(
            "/order/brand-my",
            params={"fromTs": 1, "toTs": 2},
            op_name="test",
        ):
            collected.append(doc)
            if len(collected) > 250:
                # Hard stop in case the warning was deleted and we loop forever.
                break
    finally:
        await adapter._client._client.aclose()
        # adapter.__aexit__ would try to close the original (now replaced)
        # client — skip it; the manual aclose above is enough.

    # We got exactly 100 docs from the single page.
    assert len(collected) == 100, (
        f"Expected exactly 100 docs (Slesh hard cap); got {len(collected)}. "
        f"Either the cap changed or the loop guard is broken."
    )

    # The DATA LOSS warning must have fired.
    warning_lines = [
        r.message for r in caplog.records if r.levelno >= logging.WARNING
    ]
    matching = [m for m in warning_lines if "DATA LOSS" in m]
    assert matching, (
        f"Expected a 'DATA LOSS' warning when chunk is truncated. "
        f"Got warnings: {warning_lines}"
    )
