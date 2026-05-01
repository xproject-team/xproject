"""SleshAdapter live integration test — the ONLY test that hits real Slesh.

This file contains exactly ONE test, marked `@pytest.mark.live`. It is
deliberately minimal: it calls the safest possible Slesh endpoint
(`GET /brand/my`) and verifies the entire adapter pipeline works
end-to-end against the real API.

WHEN IT RUNS:
  - NEVER on `pytest` (default — `live` marker is excluded)
  - NEVER in CI (no SLESH_API_TOKEN secret configured there)
  - ONLY when invoked manually:    pytest -m live
  - Auto-skips if SLESH_API_TOKEN is missing (safe on fresh checkouts)

WHEN TO RUN IT:
  - After rotating the Slesh API token
  - After modifying any layer of the adapter (client/limiter/retry/slesh)
  - Before a Sundance dry-run (smoke test that integration is healthy)

WHAT IT PROVES:
  - Token works against real Slesh production
  - Network path: httpx → DNS → TLS → bearer auth → JSON response
  - Schema parsing on real data (not just fixtures)
  - The full pipeline: limiter -> retry+breaker -> client -> parse -> Brand
  - Adapter is bound to the right brand (Sundance)

WHAT IT DOES NOT TEST:
  - Pagination across multiple pages (covered by unit tests with fixtures)
  - List endpoints (covered by unit tests; would burn quota)
  - Order streaming (covered by unit tests)
  - Failure scenarios (those are unit-test territory by design)

Spec: docs/slesh-integration-roadmap.md §B3.9
"""
from __future__ import annotations

import os

import pytest

from app.core.config import settings
from app.modules.pos.adapters.slesh import SleshAdapter
from app.modules.pos.schemas         import Brand


# Skip the entire file if the token isn't loaded — protects against
# accidentally trying to run live tests on a fresh laptop or in CI.
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not settings.slesh_api_token,
        reason="SLESH_API_TOKEN not set — live test cannot run",
    ),
]


@pytest.mark.asyncio
async def test_verify_token_against_real_slesh():
    """Sanity check: the full adapter pipeline reaches Slesh and returns Brand.

    This call goes through every layer we built in B3:
      SleshAdapter.verify_token()
       -> retry_with_backoff(...)
       -> TokenBucketLimiter.acquire()
       -> SleshHTTPClient.get('/brand/my', params={'brandId': ...})
       -> httpx → real HTTPS call to api.slesh.it
       -> response → JSON parse → Brand.model_validate(...)
       -> return Brand
    """
    async with SleshAdapter(
        token              = settings.slesh_api_token,
        brand_id           = settings.slesh_brand_id,
        base_url           = settings.slesh_base_url,
        request_timeout    = settings.slesh_request_timeout,
        rate_limit_rps     = settings.slesh_rate_limit_rps,
        max_retries        = settings.slesh_max_retries,
    ) as adapter:
        brand = await adapter.verify_token()

    # Real production assertions — no mocks, real Sundance brand
    assert isinstance(brand, Brand), f"expected Brand, got {type(brand).__name__}"
    assert brand.id == settings.slesh_brand_id, (
        f"adapter returned brand {brand.id} but settings configured for "
        f"{settings.slesh_brand_id} — token may be bound to a different brand"
    )
    assert brand.name, "brand must have a non-empty name"
    assert brand.is_enabled, "brand should be enabled in production"
