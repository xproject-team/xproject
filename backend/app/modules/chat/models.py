"""SQLAlchemy ORM models for the chat module."""
from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, nullable=False)
    user_id = Column(Integer, nullable=False)
    role = Column(String, nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=True)
