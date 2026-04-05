"""FastAPI WebSocket router — accepts client connections scoped to a specific event."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.realtime.manager import ConnectionManager

router = APIRouter()
manager = ConnectionManager()


@router.websocket("/events/{event_id}")
async def websocket_endpoint(websocket: WebSocket, event_id: int) -> None:
    """Accept and maintain a WebSocket connection for the given event_id.

    Broadcasts any received text message to all other clients watching
    the same event. Background workers push updates via the publisher.
    """
    await manager.connect(websocket, event_id)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(event_id, data)
    except WebSocketDisconnect:
        manager.disconnect(websocket, event_id)
