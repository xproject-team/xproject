"""Business logic for the chat module — AI assistant powered by the Anthropic Claude API."""
from sqlalchemy.ext.asyncio import AsyncSession


class ChatService:
    """Handles AI chat interactions for event staff.

    Maintains per-event conversation history and calls the Claude API
    with a system prompt that gives it access to current event metrics.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
