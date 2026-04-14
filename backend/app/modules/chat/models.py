"""SQLAlchemy ORM models for the chat module.

Three tables:
  - Channel:        a conversation container (per-bar, DM, or general)
  - ChannelMember:  who can see a channel + their unread state
  - ChatMessage:    actual messages

Design rationale: industry-standard Slack-style schema.
- Channels separate from messages = supports multiple channel types without bloat
- channel_members join table = explicit, indexed permission check
- last_read_at on membership = drives unread count without a separate reads table
- bar_id on channel (not message) = no per-message permission check needed
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenancy import TenantScopedModel, _utcnow


class Channel(TenantScopedModel):
    """A conversation container. Tenant-scoped.

    channel_type values:
      - 'bar':     scoped to a single bar (bar_id set)
      - 'dm':      direct message between 2 users (bar_id NULL, members are the 2 users)
      - 'general': company-wide announcement channel (bar_id NULL, all users members)
    """

    __tablename__ = "channels"

    channel_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
    )
    bar_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("bars.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class ChannelMember(TenantScopedModel):
    """Membership: which users can see/participate in a channel.

    A channel's permission check is: is_member(user_id, channel_id).
    last_read_at drives unread counts (messages with created_at > last_read_at).
    """

    __tablename__ = "channel_members"
    __table_args__ = (
        UniqueConstraint("channel_id", "user_id", name="uq_channel_members_channel_user"),
    )

    channel_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )


class ChatMessage(TenantScopedModel):
    """A message posted in a channel.

    Cascade behavior:
      - Delete channel → all messages deleted
      - Delete sender user → message preserved with sender_id=NULL (history kept)
    """

    __tablename__ = "chat_messages"

    channel_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
class ChatMention(TenantScopedModel):
    """A user mentioned in a chat message (e.g. '@Omar' → one row).

    read_at:
      - NULL   = unread, appears in the mention bell
      - set    = user has dismissed it
    """

    __tablename__ = "chat_mentions"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_chat_mentions_message_user"),
    )

    message_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

