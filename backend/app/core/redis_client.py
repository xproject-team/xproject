"""aioredis connection pool and pub/sub helpers — all Redis access goes through here."""
from redis.asyncio import Redis

from app.core.config import settings

_redis: Redis | None = None


async def get_redis() -> Redis:
    """Return the global Redis client, creating it on first call."""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def publish(channel: str, message: str) -> None:
    """Publish a message to a Redis pub/sub channel."""
    r = await get_redis()
    await r.publish(channel, message)
