"""HTTP router for the chat module.

Endpoints (all require valid JWT):
  GET  /chat/channels                          — list user's channels + unread counts
  GET  /chat/channels/{channel_id}/messages    — load latest N messages
  POST /chat/channels/{channel_id}/messages    — post a new message
  POST /chat/channels/{channel_id}/read        — mark channel as read
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.chat.schemas import (
    ChannelResponse,
    MentionResponse,
    MessageCreate,
    MessageResponse,
)
from app.modules.chat.service import ChatService


router = APIRouter()


# ─── Channels ─────────────────────────────────────────────────────────


@router.get("/channels", response_model=list[ChannelResponse])
async def list_channels(
    current_user: Annotated[User, Depends(get_current_user)],
    db:           Annotated[AsyncSession, Depends(get_db)],
) -> list[ChannelResponse]:
    """List all channels the current user is a member of."""
    service = ChatService(db)
    rows = await service.list_user_channels(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )
    return [
        ChannelResponse(
            id=str(row["channel"].id),
            channel_type=row["channel"].channel_type,
            bar_id=str(row["channel"].bar_id) if row["channel"].bar_id else None,
            name=row["channel"].name,
            unread_count=row["unread_count"],
            last_message_at=row["last_message_at"],
        )
        for row in rows
    ]


# ─── Messages ─────────────────────────────────────────────────────────


@router.get(
    "/channels/{channel_id}/messages",
    response_model=list[MessageResponse],
)
async def list_messages(
    channel_id:   UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db:           Annotated[AsyncSession, Depends(get_db)],
    limit:        Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MessageResponse]:
    """Load latest `limit` messages for a channel (newest first)."""
    service = ChatService(db)
    rows = await service.get_channel_messages(
        channel_id=channel_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        limit=limit,
    )
    return [
        MessageResponse(
            id=str(row["message"].id),
            channel_id=str(row["message"].channel_id),
            sender_id=str(row["message"].sender_id) if row["message"].sender_id else None,
            sender_name=row["sender_name"],
            body=row["message"].body,
            created_at=row["message"].created_at,
            edited_at=row["message"].edited_at,
        )
        for row in rows
    ]


@router.post(
    "/channels/{channel_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_message(
    channel_id:   UUID,
    payload:      MessageCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db:           Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    """Post a new message to a channel. Returns the created message."""
    service = ChatService(db)
    message = await service.post_message(
        channel_id=channel_id,
        sender_id=current_user.id,
        tenant_id=current_user.tenant_id,
        body=payload.body,
    )
    return MessageResponse(
        id=str(message.id),
        channel_id=str(message.channel_id),
        sender_id=str(message.sender_id),
        sender_name=current_user.full_name,
        body=message.body,
        created_at=message.created_at,
        edited_at=message.edited_at,
    )


# ─── Edit / Delete ────────────────────────────────────────────────────


@router.patch(
    "/messages/{message_id}",
    response_model=MessageResponse,
)
async def edit_message(
    message_id:   UUID,
    payload:      MessageCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db:           Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    """Edit a message. Only the original sender may edit their own messages."""
    service = ChatService(db)
    message = await service.edit_message(
        message_id=message_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        new_body=payload.body,
    )
    return MessageResponse(
        id=str(message.id),
        channel_id=str(message.channel_id),
        sender_id=str(message.sender_id) if message.sender_id else None,
        sender_name=current_user.full_name,
        body=message.body,
        created_at=message.created_at,
        edited_at=message.edited_at,
    )


@router.delete(
    "/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_message(
    message_id:   UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db:           Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a message. Only the original sender may delete their own messages."""
    service = ChatService(db)
    await service.delete_message(
        message_id=message_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )


# ─── Read state ───────────────────────────────────────────────────────


@router.post(
    "/channels/{channel_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def mark_channel_read(
    channel_id:   UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db:           Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Update user's last_read_at on this channel to NOW (clears unread)."""
    service = ChatService(db)
    await service.mark_channel_read(
        channel_id=channel_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )
# ─── Mentions ─────────────────────────────────────────────────────────


@router.get("/mentions", response_model=list[MentionResponse])
async def list_mentions(
    current_user: Annotated[User, Depends(get_current_user)],
    db:           Annotated[AsyncSession, Depends(get_db)],
    unread_only:  Annotated[bool, Query()] = False,
    limit:        Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MentionResponse]:
    """Return recent mentions for the current user (newest first, unread prioritized)."""
    service = ChatService(db)
    rows = await service.list_mentions(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        unread_only=unread_only,
        limit=limit,
    )
    return [
        MentionResponse(
            id=str(r["mention"].id),
            channel_id=str(r["channel_id"]),
            channel_name=r["channel_name"],
            message_id=str(r["mention"].message_id),
            sender_name=r["sender_name"],
            body=r["body"],
            created_at=r["created_at"],
            read_at=r["mention"].read_at,
        )
        for r in rows
    ]


@router.post("/mentions/{mention_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_mention_read(
    mention_id:   UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db:           Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Mark one mention as read. Idempotent."""
    service = ChatService(db)
    await service.mark_mention_read(
        mention_id=mention_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )
