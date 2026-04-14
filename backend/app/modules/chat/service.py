"""Business logic for the chat module — channels, messages, permissions."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.chat.models import Channel, ChannelMember, ChatMention, ChatMessage
from app.modules.chat.mention_parser import parse_mentions
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
            from app.realtime.websocket import manager as ws_manager

            # Resolve sender's display name for the payload
            sender_name = None
            if message.sender_id:
                sender_stmt = select(User.full_name).where(User.id == message.sender_id)
                sender_name = (await self.db.execute(sender_stmt)).scalar_one_or_none()

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
                },
            }
            await ws_manager.broadcast(f"chat:{message.channel_id}", json.dumps(payload))

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
                await ws_manager.broadcast(f"user:{uid}", json.dumps(mention_payload))
        except Exception:
            pass  # broadcast is best-effort; DB is source of truth

        return message

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
            from app.realtime.websocket import manager as ws_manager

            sender_stmt = select(User.full_name).where(User.id == message.sender_id)
            sender_name = (await self.db.execute(sender_stmt)).scalar_one_or_none()

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
                },
            }
            await ws_manager.broadcast(f"chat:{message.channel_id}", json.dumps(payload))
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
            from app.realtime.websocket import manager as ws_manager
            payload = {
                "type":       "message_deleted",
                "channel_id": str(channel_id),
                "message_id": message_id_str,
            }
            await ws_manager.broadcast(f"chat:{channel_id}", json.dumps(payload))
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
