"""Business logic for the auth module — authentication, token issuance, user lookup."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password

class InvalidOldPasswordError(Exception):
    """Raised when the supplied old_password does not match the user's hash."""


class WeakPasswordError(Exception):
    """Raised when the new_password fails strength validation (length, etc.)."""


class SameAsOldPasswordError(Exception):
    """Raised when the new_password is identical to the old."""

from app.modules.auth.models import User, UserRole


class AuthService:
    """Handles authentication and user management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def authenticate_user(self, email: str, password: str) -> User | None:
        """Verify email + password. Returns User if valid, None otherwise.

        Returns None for: unknown email, wrong password, or inactive user.
        Caller does NOT get to know which case — same response for security.
        """
        stmt = select(User).where(User.email == email.lower())
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            return None
        if not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None

        return user

    async def change_password(
        self,
        user: User,
        old_password: str,
        new_password: str,
    ) -> None:
        """Update the user's password hash after validating the old one.

        Raises:
          InvalidOldPasswordError   if old_password does not match the stored hash
          WeakPasswordError         if new_password is shorter than 8 characters
          SameAsOldPasswordError    if new_password equals old_password

        On success: persists the new bcrypt hash and commits.
        """
        if not verify_password(old_password, user.hashed_password):
            raise InvalidOldPasswordError()
        if len(new_password) < 8:
            raise WeakPasswordError()
        if new_password == old_password:
            raise SameAsOldPasswordError()
        user.hashed_password = hash_password(new_password)
        self.db.add(user)
        await self.db.commit()

    def create_user_token(
        self,
        user: User,
        active_role: UserRole | None = None,
        expires_delta: timedelta | None = None,
    ) -> str:
        """Issue a JWT containing this user's identity claims.

        Claims:
          sub:          user UUID (subject)
          email:        user email
          role:         legacy claim — user's primary role (kept for backward compat)
          active_role:  the role this token authorizes (Phase 1B); falls back to role
          tenant_id:    tenant UUID (scopes all subsequent queries)
          bar_id:       bar UUID or None (managers/bartenders only)

        active_role defaults to user.role when omitted, preserving old call-site
        behavior. Phase 1D will drop the legacy `role` claim entirely.
        """
        chosen = active_role.value if active_role is not None else user.role.value
        claims = {
            "sub":         str(user.id),
            "email":       user.email,
            "role":        user.role.value,
            "active_role": chosen,
            "tenant_id":   str(user.tenant_id),
            "bar_id":      str(user.bar_id) if user.bar_id else None,
        }
        return create_access_token(claims, expires_delta=expires_delta)

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        """Load a user by ID. Used by the JWT middleware to materialize current_user."""
        stmt = select(User).where(User.id == user_id, User.is_active.is_(True))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
