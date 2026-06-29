"""Integration tests for POST /api/v1/products/match-batch.

These hit the real FastAPI app with the real DB. The Owner account
already has a tenant with some products from previous setup work; we
don\'t mutate them, just query for matches.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_match_batch_returns_one_result_per_query(
    client: AsyncClient,
    owner_headers: dict[str, str],
) -> None:
    """The response keeps result order aligned with the input queries
    so the frontend can render them side-by-side with the source items."""
    resp = await client.post(
        "/api/v1/products/match-batch",
        headers=owner_headers,
        json={
            "queries": [
                "BIRRA HEINEKEN 30 LT FS",
                "WYBOROWA 1LT VODKA",
                "ACQ LEVISSIMA RPET NAT 50CLX24",
            ],
            "threshold": 60,
            "top_k": 3,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["results"]) == 3
    for r in data["results"]:
        assert "query" in r and "matches" in r
        for m in r["matches"]:
            assert "product_id" in m and "name" in m and "score" in m
            assert 60 <= m["score"] <= 100


@pytest.mark.asyncio
async def test_match_batch_requires_authentication(client: AsyncClient) -> None:
    """No auth → 401."""
    resp = await client.post(
        "/api/v1/products/match-batch",
        json={"queries": ["anything"]},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_match_batch_rejects_empty_query_list(
    client: AsyncClient,
    owner_headers: dict[str, str],
) -> None:
    """Empty queries → 422 from Pydantic (min_length=1)."""
    resp = await client.post(
        "/api/v1/products/match-batch",
        headers=owner_headers,
        json={"queries": []},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_match_batch_preserves_query_order(
    client: AsyncClient,
    owner_headers: dict[str, str],
) -> None:
    """Results array stays in input order even when matches differ."""
    queries = ["AAA NONSENSE", "BBB ALSO NONSENSE", "HEINEKEN"]
    resp = await client.post(
        "/api/v1/products/match-batch",
        headers=owner_headers,
        json={"queries": queries, "threshold": 60},
    )
    assert resp.status_code == 200
    data = resp.json()
    returned_queries = [r["query"] for r in data["results"]]
    assert returned_queries == queries
