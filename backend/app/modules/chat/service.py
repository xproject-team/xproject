"""Business logic for the chat module — channels, messages, permissions."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.chat.models import Channel, ChannelMember, ChatMessage


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
        return message

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
