"""Business logic for the chat module — channels, messages, permissions.

Access model (Phase 2 two-role redesign):
  Membership is DERIVED FROM ROLE, not stored. ChannelMember rows are no
  longer permission — they only carry the per-user last_read_at cursor,
  lazily created on first read. The derived check gates by channel type:

    bar / general   → Owner + Manager (every active user in the tenant)
    strategic       → Owner ONLY (most likely to hold sensitive discussion;
                      deriving it to everyone would silently widen access
                      vs the old row model)
    direct / dm     → still row-based: a DM is private between two people
    anything else   → Owner only (fail closed for unknown future types)

  Channels of COMPLETED / CANCELLED events are read-only archives: posting,
  editing, deleting, and attaching are rejected with 409.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User, UserRole
from app.modules.bars.models import Bar
from app.modules.events.models import Event, EventStatus
from app.modules.chat.models import ChatAttachment, Channel, ChannelMember, ChatMention, ChatMessage
from app.modules.chat.mention_parser import parse_mentions
from app.core import storage
import json

logger = logging.getLogger(__name__)

# Channel types whose access derives from role (no member rows involved)
ROLE_DERIVED_TYPES = ("bar", "general")
STRATEGIC_TYPES = ("strategic",)
DM_TYPES = ("direct", "dm")  # docstring says 'dm', seed data wrote 'direct' — accept both

ARCHIVED_EVENT_STATUSES = (EventStatus.COMPLETED, EventStatus.CANCELLED)


def role_may_access_channel_type(role: UserRole, channel_type: str) -> bool:
    """Pure derived-access rule for non-DM channels (DMs are row-based).

    Owner+Manager for bar/general; Owner only for strategic and for any
    unknown future type (fail closed).
    """
    if channel_type in ROLE_DERIVED_TYPES:
        return role in (UserRole.OWNER, UserRole.MANAGER)
    return role == UserRole.OWNER


class ChatService:
    """Business logic for chat: channels, messages, permissions."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Permission helpers ───────────────────────────────────────────

    async def _get_channel(self, channel_id: UUID, tenant_id: UUID) -> Channel:
        """Load a channel within the tenant. 404 if absent — cross-tenant
        requests get the same 404 as a nonexistent id (no existence leak)."""
        stmt = select(Channel).where(
            and_(Channel.id == channel_id, Channel.tenant_id == tenant_id)
        )
        channel = (await self.db.execute(stmt)).scalar_one_or_none()
        if channel is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Channel not found",
            )
        return channel

    async def _ensure_access(self, channel_id: UUID, user: User) -> Channel:
        """Raise 404/403 unless `user` may access the channel; return it.

        Role-derived for bar/general/strategic; row-based for DMs.
        """
        channel = await self._get_channel(channel_id, user.tenant_id)

        if channel.channel_type in DM_TYPES:
            member_stmt = select(ChannelMember.id).where(
                and_(
                    ChannelMember.channel_id == channel.id,
                    ChannelMember.user_id == user.id,
                    ChannelMember.tenant_id == user.tenant_id,
                )
            )
            if (await self.db.execute(member_stmt)).scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not a member of this conversation",
                )
            return channel

        if not role_may_access_channel_type(user.role, channel.channel_type):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not have access to this channel",
            )
        return channel

    async def _channel_event_status(self, channel: Channel) -> EventStatus | None:
        """The status of the event this bar channel belongs to (None for
        event-less channels: DMs, strategic, general)."""
        if channel.bar_id is None:
            return None
        stmt = (
            select(Event.status)
            .join(Bar, Bar.event_id == Event.id)
            .where(Bar.id == channel.bar_id)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _ensure_not_archived(self, channel: Channel) -> None:
        """Raise 409 for write operations on a completed/cancelled event's
        channel — archives are read-only, enforced here rather than only
        hidden in the UI."""
        event_status = await self._channel_event_status(channel)
        if event_status in ARCHIVED_EVENT_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This event has ended — its chat is archived and read-only",
            )

    # ─── Public methods ───────────────────────────────────────────────

    async def list_user_channels(self, user: User) -> list[dict]:
        """Return all channels this user can access, with unread counts and
        the owning event (for the current-vs-archived sidebar grouping).

        Access is role-derived (see module docstring); the member row, when
        present, only supplies last_read_at. One aggregated query — the old
        implementation ran 2 extra queries per channel.

        Each row: {channel, unread_count, last_message_at,
                   event_id, event_name, event_status, event_scheduled_at}
        """
        member_subq = (
            select(ChannelMember.channel_id, ChannelMember.last_read_at)
            .where(
                and_(
                    ChannelMember.user_id == user.id,
                    ChannelMember.tenant_id == user.tenant_id,
                )
            )
            .subquery()
        )

        # Visibility predicate mirrors _ensure_access, in SQL form
        dm_with_row = and_(
            Channel.channel_type.in_(DM_TYPES),
            member_subq.c.channel_id.isnot(None),
        )
        if user.role == UserRole.OWNER:
            # Owner: everything except DMs they aren't party to
            access_pred = or_(Channel.channel_type.notin_(DM_TYPES), dm_with_row)
        else:
            access_pred = or_(Channel.channel_type.in_(ROLE_DERIVED_TYPES), dm_with_row)

        # Unread = messages newer than last_read_at, excluding own messages.
        # is_distinct_from (not !=) so messages from DELETED senders
        # (sender_id NULL) still count — plain != is SQL-NULL against NULL
        # and silently undercounted them.
        unread_expr = func.count(ChatMessage.id).filter(
            and_(
                ChatMessage.sender_id.is_distinct_from(user.id),
                or_(
                    member_subq.c.last_read_at.is_(None),
                    ChatMessage.created_at > member_subq.c.last_read_at,
                ),
            )
        )

        stmt = (
            select(
                Channel,
                Event.id.label("event_id"),
                Event.name.label("event_name"),
                Event.status.label("event_status"),
                Event.scheduled_at.label("event_scheduled_at"),
                func.max(ChatMessage.created_at).label("last_message_at"),
                unread_expr.label("unread_count"),
            )
            .select_from(Channel)
            .outerjoin(member_subq, member_subq.c.channel_id == Channel.id)
            .outerjoin(Bar, Bar.id == Channel.bar_id)
            .outerjoin(Event, Event.id == Bar.event_id)
            .outerjoin(ChatMessage, ChatMessage.channel_id == Channel.id)
            .where(and_(Channel.tenant_id == user.tenant_id, access_pred))
            .group_by(Channel.id, Event.id, member_subq.c.last_read_at)
            .order_by(Channel.name)
        )
        rows = (await self.db.execute(stmt)).all()

        return [
            {
                "channel": row.Channel,
                "unread_count": row.unread_count,
                "last_message_at": row.last_message_at,
                "event_id": row.event_id,
                "event_name": row.event_name,
                "event_status": row.event_status,
                "event_scheduled_at": row.event_scheduled_at,
            }
            for row in rows
        ]

    async def list_channel_members(self, channel_id: UUID, user: User) -> list[User]:
        """The REAL current members of a channel, for the mention picker
        and the channel header — derived the same way access is:

          bar/general → every active Owner + Manager in the tenant
          strategic   → active Owners only
          direct/dm   → the users with member rows

        Requires access to the channel.
        """
        channel = await self._ensure_access(channel_id, user)

        if channel.channel_type in DM_TYPES:
            stmt = (
                select(User)
                .join(ChannelMember, ChannelMember.user_id == User.id)
                .where(
                    and_(
                        ChannelMember.channel_id == channel.id,
                        User.is_active.is_(True),
                    )
                )
                .order_by(User.full_name)
            )
        else:
            allowed_roles = (
                (UserRole.OWNER,)
                if channel.channel_type not in ROLE_DERIVED_TYPES
                else (UserRole.OWNER, UserRole.MANAGER)
            )
            stmt = (
                select(User)
                .where(
                    and_(
                        User.tenant_id == user.tenant_id,
                        User.is_active.is_(True),
                        User.role.in_(allowed_roles),
                    )
                )
                .order_by(User.full_name)
            )
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_channel_messages(
        self,
        channel_id: UUID,
        user: User,
        limit: int = 50,
    ) -> list[dict]:
        """Return latest N messages (newest first), with sender names joined.

        Permission: role-derived access (DMs row-based). Archived channels
        stay readable — only writes are blocked.
        """
        await self._ensure_access(channel_id, user)
        user_id, tenant_id = user.id, user.tenant_id

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
        user: User,
        body: str,
        attachment_ids: list[UUID] | None = None,
    ) -> ChatMessage:
        """Post a new message to a channel.

        Permission: role-derived access (DMs row-based). 409 when the
        channel's event is completed/cancelled — archives are read-only.
        """
        channel = await self._ensure_access(channel_id, user)
        await self._ensure_not_archived(channel)
        sender_id, tenant_id = user.id, user.tenant_id

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
        # Candidate pool = every active user in the tenant. Under the
        # two-role model that IS the member set of bar/general channels
        # (Owner + Managers), so no per-channel scoping is needed.
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
            # The message is already committed; mentions are a bonus —
            # but swallowing silently hid every parser bug, so log it.
            logger.warning("mention parsing failed for message %s", message.id, exc_info=True)

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
            # Broadcast is best-effort; DB is source of truth. Logged so a
            # dead Redis doesn't silently turn live chat into pull-to-refresh.
            logger.warning("chat broadcast failed for message %s", message.id, exc_info=True)

        return message

    async def create_attachment_slot(
        self,
        channel_id:   UUID,
        user:         User,
        filename:     str,
        content_type: str,
        size_bytes:   int,
    ) -> tuple[ChatAttachment, str]:
        """Create an upload slot and return (attachment_row, presigned_upload_url).

        Verifies channel access before issuing the URL, and refuses archived
        channels (attachments are a write). The attachment row is created NOW
        (with message_id=None); the message is created later on send.
        """
        channel = await self._ensure_access(channel_id, user)
        await self._ensure_not_archived(channel)
        user_id, tenant_id = user.id, user.tenant_id

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
        user:       User,
        limit:      int = 30,
    ) -> list[dict]:
        """Full-text search across all channels the user can access.

        Returns list of dicts:
            { "message": ChatMessage, "channel_name": str, "sender_name": str, "rank": float }

        Uses Postgres' ts_rank for relevance ordering. Results scoped to:
        - Same tenant as the searcher
        - Only channels the role-derived access model grants (DMs row-based)
        """
        # Empty query short-circuits to empty results (avoid expensive wildcard)
        q = query.strip()
        if not q:
            return []

        user_id, tenant_id = user.id, user.tenant_id

        from sqlalchemy import func, literal

        # plainto_tsquery: escapes user input safely. Stemming applied.
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import REGCONFIG
        tsq = func.plainto_tsquery(cast(literal("english"), REGCONFIG), q)

        # Subquery: channels this user may access — same predicate shape as
        # list_user_channels (role-derived; DMs need a member row)
        dm_member_subq = (
            select(ChannelMember.channel_id)
            .where(
                and_(
                    ChannelMember.user_id == user_id,
                    ChannelMember.tenant_id == tenant_id,
                )
            )
            .scalar_subquery()
        )
        dm_with_row = and_(
            Channel.channel_type.in_(DM_TYPES),
            Channel.id.in_(dm_member_subq),
        )
        if user.role == UserRole.OWNER:
            access_pred = or_(Channel.channel_type.notin_(DM_TYPES), dm_with_row)
        else:
            access_pred = or_(Channel.channel_type.in_(ROLE_DERIVED_TYPES), dm_with_row)
        members_subq = (
            select(Channel.id)
            .where(and_(Channel.tenant_id == tenant_id, access_pred))
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
        # Archived channels are read-only — history can't be rewritten
        channel = await self._get_channel(message.channel_id, tenant_id)
        await self._ensure_not_archived(channel)

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
            logger.warning("edit broadcast failed for message %s", message.id, exc_info=True)

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
        # Archived channels are read-only — history can't be rewritten
        channel = await self._get_channel(message.channel_id, tenant_id)
        await self._ensure_not_archived(channel)

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
            logger.warning("delete broadcast failed for message %s", message_id_str, exc_info=True)

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

    async def mark_channel_read(self, channel_id: UUID, user: User) -> None:
        """Update user's last_read_at on this channel to NOW.

        Member rows are no longer permission — they're only the per-user
        read cursor, lazily created here on first use.
        """
        await self._ensure_access(channel_id, user)

        stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == channel_id,
                ChannelMember.user_id == user.id,
                ChannelMember.tenant_id == user.tenant_id,
            )
        )
        member = (await self.db.execute(stmt)).scalar_one_or_none()
        if member is None:
            member = ChannelMember(
                tenant_id=user.tenant_id,
                channel_id=channel_id,
                user_id=user.id,
            )
            self.db.add(member)
        member.last_read_at = datetime.now(timezone.utc)
        await self.db.commit()
# ─── Auto-provision hook used by BarService.create_bar ────────────
    # Idempotent: returns the existing channel if one already exists
    # for this bar. Does NOT commit — the caller's transaction governs.

    async def create_bar_channel(
        self,
        bar_id:    UUID,
        bar_name:  str,
        tenant_id: UUID,
    ) -> Channel:
        """Create (or return existing) the 'Bar Team: <name>' channel."""
        existing_stmt = select(Channel).where(
            and_(
                Channel.bar_id == bar_id,
                Channel.channel_type == "bar",
                Channel.tenant_id == tenant_id,
            )
        )
        existing = (await self.db.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            return existing

        owner_stmt = select(User).where(
            and_(
                User.tenant_id == tenant_id,
                User.role == UserRole.OWNER,
                User.is_active.is_(True),
            )
        )
        owner = (await self.db.execute(owner_stmt)).scalar_one_or_none()

        channel = Channel(
            tenant_id    = tenant_id,
            channel_type = "bar",
            bar_id       = bar_id,
            name         = f"Bar Team: {bar_name}",
            created_by   = owner.id if owner is not None else None,
        )
        self.db.add(channel)
        await self.db.flush()

        # No member enrollment: access is role-derived (Owner + Managers see
        # every bar channel automatically); member rows appear lazily as
        # read cursors when someone first opens the channel.
        return channel