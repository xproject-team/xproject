"""Redis pub/sub → WebSocket bridge.

Background workers publish JSON messages to Redis channels named
'event:{event_id}'. This subscriber listens to all such channels and
forwards the messages to WebSocket clients via the ConnectionManager.
"""
from app.core.redis_client import get_redis
from app.realtime.manager import ConnectionManager


async def start_subscriber(manager: ConnectionManager) -> None:
    """Subscribe to all event:* Redis channels and relay messages to WebSocket clients.

    Run this as an asyncio task on application startup.
    """
    r = await get_redis()
    pubsub = r.pubsub()
    await pubsub.psubscribe("event:*")
    async for message in pubsub.listen():
        if message["type"] != "pmessage":
            continue
        try:
            channel: str = message["channel"]
            event_id = int(channel.split(":")[1])
            await manager.broadcast(event_id, message["data"])
        except (ValueError, IndexError, KeyError):
            continue
