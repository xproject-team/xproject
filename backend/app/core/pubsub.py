"""Redis pub/sub for cross-instance WebSocket broadcasts.

Why this exists:
    The in-memory ConnectionManager only knows about WebSocket clients
    connected to ITS process. With 1 backend instance that's fine. With
    2+ instances behind a load balancer, a message posted via instance A
    must reach clients connected to instance B. Redis pub/sub bridges them.

Architecture:
    - Each backend instance subscribes to ALL `chat:{channel_id}` channels
      it currently has WebSocket subscribers for
    - When a backend handles a POST that needs broadcasting, it publishes
      to the corresponding Redis channel
    - All instances (including the publisher) receive the message via their
      Redis subscription, then push to their LOCAL WebSocket clients

This means even single-instance deploys get the same code path — no
"if multi_instance: ..." branches. Redis is the source of truth for
broadcasts.

Production notes:
    - Redis pub/sub is fire-and-forget (no message persistence). If a
      backend instance is down when a message publishes, it never sees it.
      For chat this is fine because the message is also persisted to DB.
    - For guaranteed delivery (e.g. payments), use Redis Streams instead.
"""
import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis


logger = logging.getLogger(__name__)


REDIS_URL    = os.getenv("REDIS_URL", "redis://localhost:6379")
CHAT_PREFIX  = "chat:"   # Redis channel name pattern: chat:{channel_id}


class RedisBroadcaster:
    """Manages a single Redis connection + a pubsub object for subscriptions.

    Lifecycle:
        - app startup: instance is created, .start() launches the listener task
        - normal use:  .publish(channel_id, payload)  — fire and forget
                       .subscribe(channel_id)         — listener will dispatch
                       .unsubscribe(channel_id)       — stop listening
        - app shutdown: .stop() cancels the listener and closes connections

    The listener task pulls messages from Redis and dispatches each to the
    registered handler (the WebSocket ConnectionManager).
    """

    def __init__(self) -> None:
        self._publisher: aioredis.Redis | None = None
        self._subscriber: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._listener_task: asyncio.Task | None = None
        self._handler: Callable[[str, dict], Awaitable[None]] | None = None
        self._subscribed: set[str] = set()              # channel_ids
        self._lock = asyncio.Lock()

    # ─── Lifecycle ────────────────────────────────────────────────

    async def start(
        self,
        handler: Callable[[str, dict], Awaitable[None]],
    ) -> None:
        """Connect to Redis and start the background listener."""
        self._handler = handler
        self._publisher  = aioredis.from_url(REDIS_URL, decode_responses=True)
        self._subscriber = aioredis.from_url(REDIS_URL, decode_responses=True)
        self._pubsub     = self._subscriber.pubsub()

        # Sanity check
        await self._publisher.ping()
        await self._subscriber.ping()

        self._listener_task = asyncio.create_task(self._listen_loop())
        logger.info("RedisBroadcaster started (url=%s)", REDIS_URL)

    async def stop(self) -> None:
        """Cancel listener and close connections cleanly."""
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        if self._pubsub:
            await self._pubsub.close()
        if self._subscriber:
            await self._subscriber.close()
        if self._publisher:
            await self._publisher.close()

        logger.info("RedisBroadcaster stopped")

    # ─── Publish / subscribe ──────────────────────────────────────

    async def publish(self, channel_id: str, payload: dict[str, Any]) -> None:
        """Broadcast a payload to all subscribers of this channel."""
        if not self._publisher:
            logger.warning("RedisBroadcaster.publish called before start()")
            return
        await self._publisher.publish(
            f"{CHAT_PREFIX}{channel_id}",
            json.dumps(payload),
        )

    async def subscribe(self, channel_id: str) -> None:
        """Add channel_id to our Redis subscriptions (idempotent)."""
        async with self._lock:
            if channel_id in self._subscribed:
                return
            if not self._pubsub:
                return
            await self._pubsub.subscribe(f"{CHAT_PREFIX}{channel_id}")
            self._subscribed.add(channel_id)

    async def unsubscribe(self, channel_id: str) -> None:
        """Remove channel_id from Redis subscriptions (idempotent)."""
        async with self._lock:
            if channel_id not in self._subscribed:
                return
            if not self._pubsub:
                return
            await self._pubsub.unsubscribe(f"{CHAT_PREFIX}{channel_id}")
            self._subscribed.discard(channel_id)

    # ─── Internal ─────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        """Background loop: pull messages from Redis, dispatch to handler."""
        if not self._pubsub or not self._handler:
            return
        try:
            async for msg in self._pubsub.listen():
                if msg.get("type") != "message":
                    continue                                 # subscribe-acks etc.
                redis_channel = msg.get("channel", "")
                if not redis_channel.startswith(CHAT_PREFIX):
                    continue
                channel_id = redis_channel[len(CHAT_PREFIX):]
                try:
                    payload = json.loads(msg["data"])
                    await self._handler(channel_id, payload)
                except Exception as exc:                      # don't kill the loop
                    logger.exception("Error handling pub/sub message: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception:                                     # noqa: BLE001
            logger.exception("Pub/sub listener crashed")


# Module-level singleton (one per backend process)
broadcaster = RedisBroadcaster()
