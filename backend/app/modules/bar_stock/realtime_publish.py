"""Real-time pub/sub broadcasts for bar_stock + stock_transactions changes.

Centralized so both BarStockService and StockTransactionService publish on
the same channel naming convention. Frontend useDashboardSocket subscribes
to channels matching stock:{event_id}:{bar_id} for per-bar dashboard sync.

Spec: docs/bar-dashboard-spec.md S8.1 — adds 'stock:*' as the 5th pattern
alongside the existing event:* / chat:* / user:* / alerts:* publishers.

Calls are fire-and-forget: we swallow exceptions inside the helper so a
Redis hiccup never breaks the underlying mutation. The mutation already
committed by the time we try to publish; broadcast failures degrade
gracefully (frontend falls back to polling).
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


async def publish_stock_change(
    *,
    tenant_id: UUID,
    event_id: UUID,
    bar_id: UUID,
    product_id: UUID | None = None,
    change_type: str,           # 'consume' | 'return' | 'adjust' | 'create' | 'transaction'
    extra: dict[str, Any] | None = None,
) -> None:
    """Broadcast a stock-change event on channel stock:{event_id}:{bar_id}.

    The frontend subscribes to its own (event_id, bar_id) channel and
    invalidates the relevant TanStack Query caches when a message arrives.
    Owner page subscribes to the multi-bar pattern stock:{event_id}:* via
    Redis psubscribe.

    Channel format: stock:{event_id}:{bar_id} keeps tenant-implicit
    (a bar belongs to exactly one tenant, so the tenant is implied).
    """
    try:
        from app.core.redis_client import publish as _ws_publish
    except Exception as exc:  # noqa: BLE001
        # Redis client not importable — skip silently; nothing else to do.
        logger.debug("stock pub/sub: redis client unavailable: %s", exc)
        return

    channel = f"stock:{event_id}:{bar_id}"
    payload: dict[str, Any] = {
        "type": change_type,
        "tenant_id": str(tenant_id),
        "event_id": str(event_id),
        "bar_id": str(bar_id),
    }
    if product_id is not None:
        payload["product_id"] = str(product_id)
    if extra:
        payload.update(extra)

    try:
        await _ws_publish(channel, json.dumps(payload))
    except Exception as exc:  # noqa: BLE001
        logger.warning("stock pub/sub: broadcast failed on %s: %s", channel, exc)
