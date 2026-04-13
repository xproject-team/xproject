"""WebSocket connection manager — tracks active connections per subscription key.

Subscription keys are opaque strings. Examples:
  - "event:b8f14249-..."    — event-scoped live updates
  - "chat:8c359e7f-..."     — chat channel live updates
"""
from fastapi import WebSocket


class ConnectionManager:
    """Registry of active WebSocket connections, grouped by subscription key."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, key: str) -> None:
        """Accept the connection and register it under the given key."""
        await websocket.accept()
        self._connections.setdefault(key, set()).add(websocket)

    def subscribe(self, websocket: WebSocket, key: str) -> None:
        """Add an already-accepted socket to another subscription group.

        Used when one socket subscribes to multiple channels (e.g. a chat
        client watching all its channels at once).
        """
        self._connections.setdefault(key, set()).add(websocket)

    def unsubscribe(self, websocket: WebSocket, key: str) -> None:
        """Remove the socket from one subscription group (but keep others)."""
        group = self._connections.get(key)
        if group and websocket in group:
            group.discard(websocket)
            if not group:
                del self._connections[key]

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove the socket from ALL subscription groups it is in."""
        for key in list(self._connections.keys()):
            self.unsubscribe(websocket, key)

    async def broadcast(self, key: str, message: str) -> None:
        """Send a text message to all sockets subscribed to this key.

        Automatically drops dead connections encountered during send.
        """
        group = self._connections.get(key, set())
        dead: list[WebSocket] = []
        for ws in list(group):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unsubscribe(ws, key)
