"""FastAPI WebSocket router — real-time subscription endpoints.

Endpoints:
  WS /ws/events/{event_id}?token=<JWT>   — event-scoped live updates
  WS /ws/chat?token=<JWT>                — chat live updates (multi-channel)

Auth: JWT is passed as a query parameter (browsers cannot set headers on
WebSocket connections). The same JWT issued by POST /auth/login works.

The chat endpoint accepts a simple JSON protocol from the client:
  → {"action": "subscribe",   "channel_id": "uuid"}   subscribe to a channel
  → {"action": "unsubscribe", "channel_id": "uuid"}   unsubscribe
  ← {"type": "message", "channel_id": "uuid", "message": {...}}  server broadcast
"""
from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.security import decode_access_token
from app.modules.auth.service import AuthService
from app.modules.chat.service import ChatService
from app.realtime.manager import ConnectionManager


router = APIRouter()
manager = ConnectionManager()


# ─── Auth helper for WebSockets ────────────────────────────────────────


async def _authenticate_ws(token: str | None, db: AsyncSession):
    """Decode JWT, return User or None. Used by WebSocket endpoints only."""
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id_str = payload.get("sub")
        if user_id_str is None:
            return None
        user_id = UUID(user_id_str)
    except (JWTError, ValueError, TypeError):
        return None

    service = AuthService(db)
    return await service.get_user_by_id(user_id)


# ─── /ws/events/{event_id} (legacy, now JWT-protected & UUID-based) ─────


@router.websocket("/events/{event_id}")
async def websocket_events(
    websocket: WebSocket,
    event_id:  UUID,
    token:     str | None = Query(default=None),
) -> None:
    """Event-scoped live updates. Used by dashboards for real-time refresh."""
    async with AsyncSessionLocal() as db:
        user = await _authenticate_ws(token, db)

    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    key = f"event:{event_id}"
    await manager.connect(websocket, key)
    try:
        while True:
            # Echo keeps the connection alive; real updates come from
            # server-side calls to manager.broadcast(key, ...).
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ─── /ws/chat (new: multi-channel chat subscription) ────────────────────


@router.websocket("/chat")
async def websocket_chat(
    websocket: WebSocket,
    token:     str | None = Query(default=None),
) -> None:
    """Multi-channel chat subscription.

    After connecting, client sends subscribe/unsubscribe messages to
    manage which channels it receives broadcasts for. The server
    enforces channel membership (403-equivalent: silently drops the
    subscribe request) before adding to the broadcast group.
    """
    async with AsyncSessionLocal() as db:
        user = await _authenticate_ws(token, db)

    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    # Auto-subscribe user to their own user-scoped key. This is how
    # personal events (mentions, DMs, etc.) reach them regardless of
    # which channel they happen to be subscribed to. Unlike channel
    # subscriptions, this one is implicit and permanent for the lifetime
    # of the connection — no action/payload required from the client.
    user_key = f"user:{user.id}"
    manager.subscribe(websocket, user_key)

    subscribed_channels: set[str] = {user_key}

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error", "detail": "invalid JSON",
                }))
                continue

            action     = msg.get("action")
            channel_id = msg.get("channel_id")
            if not channel_id:
                continue

            if action == "subscribe":
                # Enforce membership before subscribing
                async with AsyncSessionLocal() as db:
                    chat = ChatService(db)
                    try:
                        await chat._ensure_member(
                            channel_id=UUID(channel_id),
                            user_id=user.id,
                            tenant_id=user.tenant_id,
                        )
                    except Exception:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "detail": f"not a member of {channel_id}",
                        }))
                        continue

                key = f"chat:{channel_id}"
                manager.subscribe(websocket, key)
                subscribed_channels.add(key)
                await websocket.send_text(json.dumps({
                    "type": "subscribed", "channel_id": channel_id,
                }))

            elif action == "unsubscribe":
                key = f"chat:{channel_id}"
                manager.unsubscribe(websocket, key)
                subscribed_channels.discard(key)
                await websocket.send_text(json.dumps({
                    "type": "unsubscribed", "channel_id": channel_id,
                }))

    except WebSocketDisconnect:
        manager.disconnect(websocket)
