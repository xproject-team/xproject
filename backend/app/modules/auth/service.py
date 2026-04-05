"""Business logic for the auth module — user creation, login, token issuance."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password


class AuthService:
    """Handles authentication and user management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
