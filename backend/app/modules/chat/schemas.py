"""Pydantic v2 request/response schemas for the chat module."""
from datetime import datetime

from pydantic import BaseModel


class ChatMessageCreate(BaseModel):
    content: str


class ChatMessageResponse(BaseModel):
    id: int
    event_id: int
    user_id: int
    role: str
    content: str
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
