"""Pydantic schemas for the chat module — request/response validation."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ─── Requests ──────────────────────────────────────────────────────────


class MessageCreate(BaseModel):
    """Body of a new message posted to a channel."""

    body: str = Field(..., min_length=1, max_length=4000)


# ─── Responses ─────────────────────────────────────────────────────────


class MessageResponse(BaseModel):
    """A single chat message returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    sender_id: str | None    # NULL if sender deleted (history preserved)
    sender_name: str | None  # joined from users.full_name for display
    body: str
    created_at: datetime
    edited_at: datetime | None


class ChannelResponse(BaseModel):
    """A channel returned by the API.

    `unread_count` is computed from the requesting user's last_read_at
    vs message timestamps. Driven server-side; client just displays it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_type: str         # 'bar' | 'dm' | 'general'
    bar_id: str | None
    name: str
    unread_count: int = 0
    last_message_at: datetime | None = None
class MentionResponse(BaseModel):
    """A single mention for the bell/notifications dropdown."""

    model_config = ConfigDict(from_attributes=True)

    id:          str
    channel_id:  str
    channel_name: str
    message_id:  str
    sender_name: str | None
    body:        str
    created_at:  datetime
    read_at:     datetime | None

