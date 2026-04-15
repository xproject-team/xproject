"""HTTP router for the chat module.

Endpoints (all require valid JWT):
  GET  /chat/channels                          — list user's channels + unread counts
  GET  /chat/channels/{channel_id}/messages    — load latest N messages
  POST /chat/channels/{channel_id}/messages    — post a new message
  POST /chat/channels/{channel_id}/read        — mark channel as read
"""
from typing import Annotated
from uuid import UUID

from app.core.config import settings
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.models import User
from app.modules.auth.router import get_current_user
from app.modules.chat.schemas import (
    AttachmentPresignRequest,
    AttachmentPresignResponse,
    AttachmentResponse,
    ChannelResponse,
    MentionResponse,
    MessageCreate,
    MessageResponse,
    SearchResultItem,
)
from app.core import storage as _storage
from app.modules.chat.service import ChatService


router = APIRouter()



# ─── Helpers ──────────────────────────────────────────────────────────


def _hydrate_attachments(atts) -> list[AttachmentResponse]:
    """Convert ChatAttachment ORM rows to AttachmentResponse with download URLs."""
    from app.core import storage as _storage
    return [
        AttachmentResponse(
            id=str(a.id),
            object_key=a.object_key,
            download_url=_storage.public_download_url(a.object_key),
            original_filename=a.original_filename,
            content_type=a.content_type,
            size_bytes=a.size_bytes,
        )
        for a in atts
    ]

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
    # Hydrate attachments for all messages in one batched query
    msg_ids = [row["message"].id for row in rows]
    atts_by_msg: dict = {mid: [] for mid in msg_ids}
    if msg_ids:
        from app.modules.chat.models import ChatAttachment
        from sqlalchemy import select as sa_select
        atts_stmt = sa_select(ChatAttachment).where(
            ChatAttachment.message_id.in_(msg_ids),
            ChatAttachment.tenant_id == current_user.tenant_id,
        )
        for att in (await db.execute(atts_stmt)).scalars().all():
            atts_by_msg.setdefault(att.message_id, []).append(att)

    return [
        MessageResponse(
            id=str(row["message"].id),
            channel_id=str(row["message"].channel_id),
            sender_id=str(row["message"].sender_id) if row["message"].sender_id else None,
            sender_name=row["sender_name"],
            body=row["message"].body,
            created_at=row["message"].created_at,
            edited_at=row["message"].edited_at,
            attachments=_hydrate_attachments(atts_by_msg.get(row["message"].id, [])),
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
    from uuid import UUID as _UUID
    message = await service.post_message(
        channel_id=channel_id,
        sender_id=current_user.id,
        tenant_id=current_user.tenant_id,
        body=payload.body,
        attachment_ids=[_UUID(aid) for aid in payload.attachment_ids],
    )
    atts = await service.get_message_attachments(
        message_id=message.id,
        tenant_id=current_user.tenant_id,
    )
    return MessageResponse(
        id=str(message.id),
        channel_id=str(message.channel_id),
        sender_id=str(message.sender_id),
        sender_name=current_user.full_name,
        body=message.body,
        created_at=message.created_at,
        edited_at=message.edited_at,
        attachments=_hydrate_attachments(atts),
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
    atts = await service.get_message_attachments(
        message_id=message.id,
        tenant_id=current_user.tenant_id,
    )
    return MessageResponse(
        id=str(message.id),
        channel_id=str(message.channel_id),
        sender_id=str(message.sender_id) if message.sender_id else None,
        sender_name=current_user.full_name,
        body=message.body,
        created_at=message.created_at,
        edited_at=message.edited_at,
        attachments=_hydrate_attachments(atts),
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
# ─── Attachments ──────────────────────────────────────────────────────


@router.post(
    "/attachments/presign",
    response_model=AttachmentPresignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def presign_attachment(
    payload:      AttachmentPresignRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db:           Annotated[AsyncSession, Depends(get_db)],
) -> AttachmentPresignResponse:
    """Create an upload slot. Returns the URL the client uses to PUT the file
    directly to MinIO/S3. After the upload completes, include the attachment_id
    in the message body when posting via POST /chat/channels/{id}/messages.
    """
    service = ChatService(db)
    attachment, upload_url = await service.create_attachment_slot(
        channel_id   = UUID(payload.channel_id),
        user_id      = current_user.id,
        tenant_id    = current_user.tenant_id,
        filename     = payload.filename,
        content_type = payload.content_type,
        size_bytes   = payload.size_bytes,
    )
    return AttachmentPresignResponse(
        attachment_id      = str(attachment.id),
        upload_url         = upload_url,
        object_key         = attachment.object_key,
        expires_in_seconds = _storage.PRESIGN_UPLOAD_EXPIRY_SEC,
    )
# ─── Search ───────────────────────────────────────────────────────────


@router.get(
    "/search",
    response_model=list[SearchResultItem],
)
async def search_messages_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    db:           Annotated[AsyncSession, Depends(get_db)],
    q:            Annotated[str, Query(min_length=1, max_length=200)],
    limit:        Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[SearchResultItem]:
    """Full-text search across channels the current user is a member of.

    Results ranked by relevance (ts_rank), ties broken by recency.
    Empty/blank queries return [].
    """
    service = ChatService(db)
    rows = await service.search_messages(
        query=q,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        limit=limit,
    )
    return [
        SearchResultItem(
            message_id   = str(r["message"].id),
            channel_id   = str(r["message"].channel_id),
            channel_name = r["channel_name"],
            sender_id    = str(r["message"].sender_id) if r["message"].sender_id else None,
            sender_name  = r["sender_name"],
            body         = r["message"].body,
            created_at   = r["message"].created_at,
            rank         = r["rank"],
        )
        for r in rows
    ]
