"""Business logic for the chat module — channels, messages, permissions."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.chat.models import ChatAttachment, Channel, ChannelMember, ChatMention, ChatMessage
from app.modules.chat.mention_parser import parse_mentions
from app.core import storage
import json


class ChatService:
    """Business logic for chat: channels, messages, permissions."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Permission helper ────────────────────────────────────────────

    async def _ensure_member(
        self,
        channel_id: UUID,
        user_id: UUID,
        tenant_id: UUID,
    ) -> ChannelMember:
        """Raise 403 unless user is a member of channel within tenant."""
        stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == channel_id,
                ChannelMember.user_id == user_id,
                ChannelMember.tenant_id == tenant_id,
            )
        )
        result = await self.db.execute(stmt)
        member = result.scalar_one_or_none()
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this channel",
            )
        return member

    # ─── Public methods ───────────────────────────────────────────────

    async def list_user_channels(
        self,
        user_id: UUID,
        tenant_id: UUID,
    ) -> list[dict]:
        """Return all channels this user belongs to, with unread counts.

        Each row: {channel, unread_count, last_message_at}
        """
        # Channels where user is a member
        member_subq = (
            select(ChannelMember.channel_id, ChannelMember.last_read_at)
            .where(
                and_(
                    ChannelMember.user_id == user_id,
                    ChannelMember.tenant_id == tenant_id,
                )
            )
            .subquery()
        )

        # Join channels with member info
        stmt = (
            select(Channel, member_subq.c.last_read_at)
            .join(member_subq, member_subq.c.channel_id == Channel.id)
            .where(Channel.tenant_id == tenant_id)
            .order_by(Channel.name)
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        out: list[dict] = []
        for channel, last_read_at in rows:
            # Latest message timestamp
            last_msg_stmt = select(func.max(ChatMessage.created_at)).where(
                ChatMessage.channel_id == channel.id
            )
            last_msg_at = (await self.db.execute(last_msg_stmt)).scalar_one()

            # Unread count = messages newer than last_read_at,
            # excluding the user's own messages.
            if last_read_at is None:
                unread_stmt = select(func.count(ChatMessage.id)).where(
                    and_(
                        ChatMessage.channel_id == channel.id,
                        ChatMessage.sender_id != user_id,
                    )
                )
            else:
                unread_stmt = select(func.count(ChatMessage.id)).where(
                    and_(
                        ChatMessage.channel_id == channel.id,
                        ChatMessage.created_at > last_read_at,
                        ChatMessage.sender_id != user_id,
                    )
                )
            unread = (await self.db.execute(unread_stmt)).scalar_one()

            out.append({
                "channel": channel,
                "unread_count": unread,
                "last_message_at": last_msg_at,
            })
        return out

    async def get_channel_messages(
        self,
        channel_id: UUID,
        user_id: UUID,
        tenant_id: UUID,
        limit: int = 50,
    ) -> list[dict]:
        """Return latest N messages (newest first), with sender names joined.

        Permission: user must be a member of channel.
        """
        await self._ensure_member(channel_id, user_id, tenant_id)

        # JOIN chat_messages with users for sender name
        stmt = (
            select(ChatMessage, User.full_name)
            .outerjoin(User, ChatMessage.sender_id == User.id)
            .where(
                and_(
                    ChatMessage.channel_id == channel_id,
                    ChatMessage.tenant_id == tenant_id,
                )
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {"message": msg, "sender_name": name}
            for msg, name in rows
        ]

    async def post_message(
        self,
        channel_id: UUID,
        sender_id: UUID,
        tenant_id: UUID,
        body: str,
        attachment_ids: list[UUID] | None = None,
    ) -> ChatMessage:
        """Post a new message to a channel.

        Permission: sender must be a member of channel.
        """
        await self._ensure_member(channel_id, sender_id, tenant_id)

        message = ChatMessage(
            tenant_id=tenant_id,
            channel_id=channel_id,
            sender_id=sender_id,
            body=body,
        )
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)

        # Link attachments to this message (defense-in-depth: only the
        # uploader can attach, only in the same tenant, only unlinked ones)
        if attachment_ids:
            from sqlalchemy import update as sa_update
            atts_stmt = select(ChatAttachment).where(
                and_(
                    ChatAttachment.id.in_(attachment_ids),
                    ChatAttachment.tenant_id == tenant_id,
                    ChatAttachment.uploaded_by == sender_id,
                    ChatAttachment.message_id.is_(None),
                )
            )
            valid_atts = list((await self.db.execute(atts_stmt)).scalars().all())
            if valid_atts:
                await self.db.execute(
                    sa_update(ChatAttachment)
                    .where(ChatAttachment.id.in_([a.id for a in valid_atts]))
                    .values(message_id=message.id)
                )
                await self.db.commit()

        # ─── Resolve @mentions ──────────────────────────────────────────
        # Fetch all users in the same tenant (candidate pool for the parser).
        # Scales fine for MVP — Noma Group has ~4 users. For larger tenants
        # we'd add a per-channel-members scoping instead.
        mentioned_user_ids: list[UUID] = []
        try:
            users_stmt = select(User.id, User.full_name).where(
                and_(User.tenant_id == tenant_id, User.is_active.is_(True))
            )
            users_result = await self.db.execute(users_stmt)
            candidates = [(row.id, row.full_name) for row in users_result.all()]

            mentioned_user_ids = parse_mentions(
                body=body,
                candidates=candidates,
                author_id=sender_id,
            )

            # Persist ChatMention rows (one per mentioned user)
            for uid in mentioned_user_ids:
                self.db.add(ChatMention(
                    tenant_id=tenant_id,
                    message_id=message.id,
                    user_id=uid,
                ))
            if mentioned_user_ids:
                await self.db.commit()
        except Exception:
            # Mention parsing must never fail the message post.
            # The message is already committed; mentions are a bonus.
            pass

        # Broadcast to all WebSocket subscribers of this channel.
        # Failures in broadcast must NEVER fail the REST request.
        try:
            # Lazy import breaks circular dependency (websocket.py imports ChatService)
            from app.core.redis_client import publish as _ws_publish

            # Resolve sender's display name for the payload
            sender_name = None
            if message.sender_id:
                sender_stmt = select(User.full_name).where(User.id == message.sender_id)
                sender_name = (await self.db.execute(sender_stmt)).scalar_one_or_none()

            # Build attachment payload
            from app.core import storage as _storage
            atts_for_payload = []
            if attachment_ids:
                atts_stmt = select(ChatAttachment).where(
                    ChatAttachment.message_id == message.id,
                    ChatAttachment.tenant_id == tenant_id,
                )
                for a in (await self.db.execute(atts_stmt)).scalars().all():
                    atts_for_payload.append({
                        "id":                str(a.id),
                        "object_key":        a.object_key,
                        "download_url":      _storage.public_download_url(a.object_key),
                        "original_filename": a.original_filename,
                        "content_type":      a.content_type,
                        "size_bytes":        a.size_bytes,
                    })

            payload = {
                "type": "message",
                "channel_id": str(message.channel_id),
                "message": {
                    "id":          str(message.id),
                    "channel_id":  str(message.channel_id),
                    "sender_id":   str(message.sender_id) if message.sender_id else None,
                    "sender_name": sender_name,
                    "body":        message.body,
                    "created_at":  message.created_at.isoformat(),
                    "edited_at":   message.edited_at.isoformat() if message.edited_at else None,
                    "attachments": atts_for_payload,
                },
            }
            await _ws_publish(f"chat:{message.channel_id}", json.dumps(payload))

            # User-scoped mention broadcasts — hit each mentioned user's
            # personal key, so they get notified regardless of what page
            # they're on (vs channel broadcast which needs them subscribed).
            for uid in mentioned_user_ids:
                mention_payload = {
                    "type": "mention",
                    "channel_id": str(message.channel_id),
                    "message_id": str(message.id),
                    "sender_name": sender_name,
                    "body": message.body,
                    "created_at": message.created_at.isoformat(),
                }
                await _ws_publish(f"user:{uid}", json.dumps(mention_payload))
        except Exception:
            pass  # broadcast is best-effort; DB is source of truth

        return message

    async def create_attachment_slot(
        self,
        channel_id:   UUID,
        user_id:      UUID,
        tenant_id:    UUID,
        filename:     str,
        content_type: str,
        size_bytes:   int,
    ) -> tuple[ChatAttachment, str]:
        """Create an upload slot and return (attachment_row, presigned_upload_url).

        Verifies the user is a member of the channel before issuing the URL.
        The attachment row is created NOW (with message_id=None); the message
        is created later when the user actually sends it.
        """
        # Membership check — only members of the channel can attach
        await self._ensure_member(
            channel_id=channel_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )

        # Size cap — 25MB. Keeps storage costs sane and prevents silly abuse.
        # Larger files would need chunked uploads (out of MVP scope).
        MAX_SIZE_BYTES = 25 * 1024 * 1024
        if size_bytes > MAX_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Max {MAX_SIZE_BYTES // (1024*1024)}MB.",
            )

        # Generate the object key + presigned URL
        object_key = storage.make_object_key(
            tenant_id=tenant_id,
            channel_id=channel_id,
            original_filename=filename,
        )
        upload_url = storage.presigned_upload_url(object_key, content_type)

        # Persist the attachment row (no message_id yet)
        att = ChatAttachment(
            tenant_id=tenant_id,
            uploaded_by=user_id,
            object_key=object_key,
            original_filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            message_id=None,                     # set later by post_message
        )
        self.db.add(att)
        await self.db.commit()
        await self.db.refresh(att)

        return att, upload_url

    async def get_message_attachments(
        self,
        message_id: UUID,
        tenant_id:  UUID,
    ) -> list[ChatAttachment]:
        """Fetch all attachments for a message."""
        stmt = select(ChatAttachment).where(
            and_(
                ChatAttachment.message_id == message_id,
                ChatAttachment.tenant_id == tenant_id,
            )
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def search_messages(
        self,
        query:      str,
        user_id:    UUID,
        tenant_id:  UUID,
        limit:      int = 30,
    ) -> list[dict]:
        """Full-text search across all channels the user is a member of.

        Returns list of dicts:
            { "message": ChatMessage, "channel_name": str, "sender_name": str, "rank": float }

        Uses Postgres' ts_rank for relevance ordering. Results scoped to:
        - Same tenant as the searcher
        - Only channels where user is an active member
        - Not soft-deleted
        """
        # Empty query short-circuits to empty results (avoid expensive wildcard)
        q = query.strip()
        if not q:
            return []

        from sqlalchemy import func, literal

        # plainto_tsquery: escapes user input safely. Stemming applied.
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import REGCONFIG
        tsq = func.plainto_tsquery(cast(literal("english"), REGCONFIG), q)

        # Subquery: channels where this user is an active member (not removed)
        members_subq = (
            select(ChannelMember.channel_id)
            .where(
                and_(
                    ChannelMember.user_id == user_id,
                    ChannelMember.tenant_id == tenant_id,
                )
            )
            .scalar_subquery()
        )

        # Main query: join messages + channel + sender for display data
        # ts_rank as the score; order newest-within-rank for ties
        stmt = (
            select(
                ChatMessage,
                Channel.name.label("channel_name"),
                User.full_name.label("sender_name"),
                func.ts_rank(ChatMessage.search_vector, tsq).label("rank"),
            )
            .join(Channel, Channel.id == ChatMessage.channel_id)
            .outerjoin(User, User.id == ChatMessage.sender_id)
            .where(
                and_(
                    ChatMessage.tenant_id == tenant_id,
                    ChatMessage.channel_id.in_(members_subq),
                    ChatMessage.search_vector.op("@@")(tsq),     # FTS match
                )
            )
            .order_by(func.ts_rank(ChatMessage.search_vector, tsq).desc(),
                      ChatMessage.created_at.desc())
            .limit(limit)
        )

        rows = (await self.db.execute(stmt)).all()

        return [
            {
                "message":      row[0],
                "channel_name": row[1],
                "sender_name":  row[2],
                "rank":         float(row[3]) if row[3] is not None else 0.0,
            }
            for row in rows
        ]

    async def edit_message(
        self,
        message_id: UUID,
        user_id:    UUID,
        tenant_id:  UUID,
        new_body:   str,
    ) -> ChatMessage:
        """Edit a message. Only the original sender may edit."""
        stmt = select(ChatMessage).where(
            and_(
                ChatMessage.id == message_id,
                ChatMessage.tenant_id == tenant_id,
            )
        )
        result = await self.db.execute(stmt)
        message = result.scalar_one_or_none()

        if message is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found",
            )
        if message.sender_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only edit your own messages",
            )

        message.body = new_body
        message.edited_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(message)

        # Broadcast edit event
        try:
            from app.core.redis_client import publish as _ws_publish

            sender_stmt = select(User.full_name).where(User.id == message.sender_id)
            sender_name = (await self.db.execute(sender_stmt)).scalar_one_or_none()

            # Re-fetch attachments for the edited message
            from app.core import storage as _storage_e
            atts_e_stmt = select(ChatAttachment).where(
                ChatAttachment.message_id == message.id,
                ChatAttachment.tenant_id == tenant_id,
            )
            edit_atts = []
            for a in (await self.db.execute(atts_e_stmt)).scalars().all():
                edit_atts.append({
                    "id":                str(a.id),
                    "object_key":        a.object_key,
                    "download_url":      _storage_e.public_download_url(a.object_key),
                    "original_filename": a.original_filename,
                    "content_type":      a.content_type,
                    "size_bytes":        a.size_bytes,
                })

            payload = {
                "type": "message_edited",
                "channel_id": str(message.channel_id),
                "message": {
                    "id":          str(message.id),
                    "channel_id":  str(message.channel_id),
                    "sender_id":   str(message.sender_id) if message.sender_id else None,
                    "sender_name": sender_name,
                    "body":        message.body,
                    "created_at":  message.created_at.isoformat(),
                    "edited_at":   message.edited_at.isoformat() if message.edited_at else None,
                    "attachments": edit_atts,
                },
            }
            await _ws_publish(f"chat:{message.channel_id}", json.dumps(payload))
        except Exception:
            pass

        return message

    async def delete_message(
        self,
        message_id: UUID,
        user_id:    UUID,
        tenant_id:  UUID,
    ) -> UUID:
        """Delete a message. Only the original sender may delete.

        Returns the channel_id of the deleted message.
        """
        stmt = select(ChatMessage).where(
            and_(
                ChatMessage.id == message_id,
                ChatMessage.tenant_id == tenant_id,
            )
        )
        result = await self.db.execute(stmt)
        message = result.scalar_one_or_none()

        if message is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found",
            )
        if message.sender_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own messages",
            )

        channel_id     = message.channel_id
        message_id_str = str(message.id)

        await self.db.delete(message)
        await self.db.commit()

        # Broadcast delete event
        try:
            from app.core.redis_client import publish as _ws_publish
            payload = {
                "type":       "message_deleted",
                "channel_id": str(channel_id),
                "message_id": message_id_str,
            }
            await _ws_publish(f"chat:{channel_id}", json.dumps(payload))
        except Exception:
            pass

        return channel_id

    async def list_mentions(
        self,
        user_id:     UUID,
        tenant_id:   UUID,
        limit:       int = 50,
        unread_only: bool = False,
    ) -> list[dict]:
        """Return this user\'s mentions (newest first), with channel + message context."""
        stmt = (
            select(
                ChatMention,
                ChatMessage.body,
                ChatMessage.created_at,
                ChatMessage.channel_id,
                Channel.name.label("channel_name"),
                User.full_name.label("sender_name"),
            )
            .join(ChatMessage, ChatMention.message_id == ChatMessage.id)
            .join(Channel, Channel.id == ChatMessage.channel_id)
            .outerjoin(User, User.id == ChatMessage.sender_id)
            .where(
                and_(
                    ChatMention.user_id == user_id,
                    ChatMention.tenant_id == tenant_id,
                )
            )
            .order_by(ChatMention.read_at.is_(None).desc(), ChatMessage.created_at.desc())
            .limit(limit)
        )
        if unread_only:
            stmt = stmt.where(ChatMention.read_at.is_(None))

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "mention":      row.ChatMention,
                "body":         row.body,
                "created_at":   row.created_at,
                "channel_id":   row.channel_id,
                "channel_name": row.channel_name,
                "sender_name":  row.sender_name,
            }
            for row in rows
        ]

    async def mark_mention_read(
        self,
        mention_id: UUID,
        user_id:    UUID,
        tenant_id:  UUID,
    ) -> None:
        """Mark one mention as read. Idempotent — no-op if already read."""
        stmt = select(ChatMention).where(
            and_(
                ChatMention.id == mention_id,
                ChatMention.user_id == user_id,      # can only mark your own
                ChatMention.tenant_id == tenant_id,
            )
        )
        result = await self.db.execute(stmt)
        mention = result.scalar_one_or_none()

        if mention is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mention not found",
            )

        if mention.read_at is None:
            mention.read_at = datetime.now(timezone.utc)
            await self.db.commit()

    async def mark_channel_read(
        self,
        channel_id: UUID,
        user_id: UUID,
        tenant_id: UUID,
    ) -> None:
        """Update user's last_read_at on this channel to NOW."""
        member = await self._ensure_member(channel_id, user_id, tenant_id)
        member.last_read_at = datetime.now(timezone.utc)
        await self.db.commit()
