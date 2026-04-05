"""WebSocket connection manager — tracks active connections per event and handles broadcast."""
from fastapi import WebSocket


class ConnectionManager:
    """Maintains the registry of active WebSocket connections, keyed by event_id."""

    def __init__(self) -> None:
        self._connections: dict[int, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, event_id: int) -> None:
        """Accept the connection and register it under event_id."""
        await websocket.accept()
        self._connections.setdefault(event_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, event_id: int) -> None:
        """Remove the connection from the registry."""
        connections = self._connections.get(event_id, [])
        if websocket in connections:
            connections.remove(websocket)

    async def broadcast(self, event_id: int, message: str) -> None:
        """Send a text message to all clients connected to event_id."""
        for ws in list(self._connections.get(event_id, [])):
            await ws.send_text(message)
