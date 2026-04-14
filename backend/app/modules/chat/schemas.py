"""Pydantic schemas for the chat module — request/response validation."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ─── Requests ──────────────────────────────────────────────────────────


class MessageCreate(BaseModel):
    """Body of a new message posted to a channel."""

    body:           str = Field(..., min_length=1, max_length=4000)
    attachment_ids: list[str] = Field(default_factory=list)


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
    attachments: list['AttachmentResponse'] = Field(default_factory=list)

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

class AttachmentPresignRequest(BaseModel):
    """Client requests an upload slot for a file."""

    channel_id:   str
    filename:     str
    content_type: str
    size_bytes:   int


class AttachmentPresignResponse(BaseModel):
    """Server returns the slot. Client uses upload_url to PUT the bytes."""

    attachment_id: str
    upload_url:    str
    object_key:    str
    expires_in_seconds: int


class AttachmentResponse(BaseModel):
    """Attachment metadata embedded in MessageResponse."""

    model_config = ConfigDict(from_attributes=True)

    id:                str
    object_key:        str
    download_url:      str
    original_filename: str
    content_type:      str
    size_bytes:        int


# Resolve forward references (AttachmentResponse defined above)
MessageResponse.model_rebuild()
