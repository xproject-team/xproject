"""Repository layer for auth module — pure DB access, no business logic.

Functions return ORM objects or domain primitives. Service layer composes
these into use cases (login, role assignment, etc.).

All helpers accept an `AsyncSession` so they participate in the caller's
transaction. They do NOT call commit/rollback — that's the caller's job.
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import User, UserRole, UserRoleAssignment


async def get_user_authorized_roles(
    db: AsyncSession,
    user_id: UUID,
) -> list[UserRole]:
    """Return every role the given user is authorized to act as.

    Driven by the `user_roles` join table (the multi-role source of truth).
    The legacy `users.role` column is intentionally NOT consulted — once
    Phase 1A backfill has run, every authorized role is in `user_roles`.

    Returns:
        Sorted list of UserRole values (deterministic order for testing).
        Empty list if the user has no role assignments or doesn't exist.
    """
    stmt = (
        select(UserRoleAssignment.role)
        .where(UserRoleAssignment.user_id == user_id)
        .order_by(UserRoleAssignment.role)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_user_by_email_with_roles(
    db: AsyncSession,
    email: str,
) -> User | None:
    """Fetch a user by email, eagerly loading their role_assignments.

    Used by `POST /auth/roles-for-email` (Phase 1B): given just an email,
    return the user with all assigned roles ready to render in the role
    picker, without a second query. Eager loading is correct here because
    the caller will always touch `role_assignments`.

    Email match is case-insensitive at the SQL level. Returns None if the
    email doesn't match any user. Inactive users (is_active=False) ARE
    returned by this helper; the service layer decides what to do with
    them (typically: behave as if user doesn't exist, to prevent
    enumeration via the role-picker step).
    """
    stmt = (
        select(User)
        .where(User.email == email.lower().strip())
        .options(selectinload(User.role_assignments))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
