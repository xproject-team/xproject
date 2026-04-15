"""Resilient Redis pub/sub → WebSocket bridge.

Listens to broadcast patterns and relays messages to local WebSocket
clients via the ConnectionManager. Built for production:

  - Exponential backoff on connection failures (Redis restarts, network blips)
  - Auto-restart if the listener loop crashes (any exception inside)
  - Structured logging so we know WHY it failed
  - Per-message error isolation (one bad message doesn't kill the loop)

Patterns subscribed:
  event:*    — event-scoped live updates
  chat:*     — chat channel broadcasts
  user:*     — user-scoped notifications (mentions, DMs, etc.)
"""
from __future__ import annotations

import asyncio
import logging

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError

from app.core.redis_client import get_redis
from app.realtime.manager import ConnectionManager


logger = logging.getLogger(__name__)


SUBSCRIBED_PATTERNS = ("event:*", "chat:*", "user:*")

# Backoff caps: start at 1s, double on each failure, max 30s
_INITIAL_BACKOFF_SEC = 1.0
_MAX_BACKOFF_SEC     = 30.0


async def start_subscriber(manager: ConnectionManager) -> None:
    """Top-level supervisor: keeps the inner loop alive forever.

    Restarts the inner loop on ANY failure (Redis disconnect, network
    blip, unexpected exception). This is what makes the system survive
    transient infrastructure issues without operator intervention.
    """
    backoff = _INITIAL_BACKOFF_SEC

    while True:
        try:
            logger.info("subscriber: starting listener loop")
            await _run_listener(manager)

            # If _run_listener returns normally (shouldn't happen unless
            # cancelled), reset backoff and try again immediately.
            backoff = _INITIAL_BACKOFF_SEC

        except asyncio.CancelledError:
            # Clean shutdown — propagate up so lifespan can exit
            logger.info("subscriber: cancelled, shutting down")
            raise

        except RedisConnectionError as exc:
            # Redis went away — log and back off
            logger.warning(
                "subscriber: redis connection lost (%s) — reconnecting in %.1fs",
                exc, backoff,
            )

        except RedisError as exc:
            # Other Redis-level error (auth, command failure, etc.)
            logger.error(
                "subscriber: redis error (%s) — retrying in %.1fs",
                exc, backoff,
            )

        except Exception:                                    # noqa: BLE001
            # Any other unexpected exception — log full traceback
            logger.exception(
                "subscriber: unexpected crash — retrying in %.1fs",
                backoff,
            )

        # Wait before retry, then double the backoff (capped)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, _MAX_BACKOFF_SEC)


async def _run_listener(manager: ConnectionManager) -> None:
    """The actual listener — pulls messages from Redis, dispatches to WS clients.

    Raises on connection failure so the supervisor can reconnect.
    Per-message exceptions are caught and logged but don't kill the loop.
    """
    r = await get_redis()

    # Verify the connection works before subscribing — a broken Redis
    # would otherwise fail mid-subscribe and leave the pubsub object
    # in a weird state.
    await r.ping()

    pubsub = r.pubsub()
    try:
        for pattern in SUBSCRIBED_PATTERNS:
            await pubsub.psubscribe(pattern)
        logger.info(
            "subscriber: subscribed to %d patterns: %s",
            len(SUBSCRIBED_PATTERNS), ", ".join(SUBSCRIBED_PATTERNS),
        )

        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue                                     # subscribe-acks etc.

            try:
                channel: str = message["channel"]
                data:    str = message["data"]
                await manager.broadcast(channel, data)
            except (KeyError, TypeError) as exc:
                # Malformed message — log and skip, don't kill the loop
                logger.warning("subscriber: skipping malformed message (%s)", exc)
            except Exception:                                # noqa: BLE001
                # Anything else inside per-message handling — log + continue
                logger.exception("subscriber: error dispatching message")
    finally:
        # On exit (normal or exceptional), unsubscribe cleanly to avoid
        # leaving subscriptions on Redis side if the connection survives.
        try:
            await pubsub.unsubscribe()
            await pubsub.close()
        except Exception:                                    # noqa: BLE001
            pass
