"""HTTP router for the auth module.

Endpoints:
  POST /auth/login   — exchange email + password for a JWT access token
  GET  /auth/me      — return the current authenticated user (requires JWT)
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.modules.auth.models import User, UserRole
from app.modules.auth.repository import (
    get_user_authorized_roles,
    get_user_by_email_with_roles,
)
from app.modules.auth.schemas import (
    RolesForEmailRequest,
    RolesForEmailResponse,
    TokenResponse,
    UserResponse,
)
from app.modules.auth.service import AuthService


router = APIRouter()

# Token-bearer dependency. tokenUrl points to where Swagger UI sends login form.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ─── Dependencies ─────────────────────────────────────────────────────────


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db:    Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Decode JWT, look up the user, return them.

    Raises 401 if token is invalid, expired, or user no longer exists / is inactive.
    Used by ANY endpoint that needs the authenticated user.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(token)
        user_id_str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    from uuid import UUID
    try:
        user_id = UUID(user_id_str)
    except (ValueError, TypeError):
        raise credentials_exc

    service = AuthService(db)
    user = await service.get_user_by_id(user_id)

    # ─── 1D-min: honor JWT active_role over DB users.role ────────────────
    # The JWT records the role the user authenticated with at /auth/login.
    # We override the in-memory User.role so every downstream guard sees
    # the JWT-correct role, not whichever role happens to be in users.role.
    # Falls back to user.role (legacy) when the claim is absent (old tokens).
    if user is not None:
        active_role_str = payload.get("active_role")
        if active_role_str:
            try:
                user.role = UserRole(active_role_str)
            except ValueError:
                # Token contains an invalid role string — treat as expired
                raise credentials_exc
    if user is None:
        raise credentials_exc
    return user


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data:      Annotated[OAuth2PasswordRequestForm, Depends()],
    db:             Annotated[AsyncSession, Depends(get_db)],
    requested_role: Annotated[str | None, Form()] = None,
) -> TokenResponse:
    """Exchange email + password (+ optional requested_role) for a JWT.

    Backward compatible: omitting requested_role behaves exactly as before
    (token's active_role defaults to the user's primary users.role).

    When requested_role is provided, the user must be authorized for that
    role in the user_roles table. 403 otherwise.

    Returns 401 on invalid credentials. Same response for unknown email and
    wrong password (prevents user enumeration attacks).
    """
    service = AuthService(db)
    user = await service.authenticate_user(form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    active: UserRole | None = None
    if requested_role is not None:
        # Validate the requested role string parses to a known enum value
        try:
            active = UserRole(requested_role.lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown role: {requested_role!r}",
            )
        # Validate the user is authorized for this role
        authorized = await get_user_authorized_roles(db, user.id)
        if active not in authorized:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not authorized for the requested role",
            )

    token = service.create_user_token(user, active_role=active)
    return TokenResponse(access_token=token, token_type="bearer")


@router.post("/roles-for-email", response_model=RolesForEmailResponse)
async def roles_for_email(
    payload: RolesForEmailRequest,
    db:      Annotated[AsyncSession, Depends(get_db)],
) -> RolesForEmailResponse:
    """Step 1 of the two-step login flow.

    Given an email, return the roles that user is authorized for. Used by
    the frontend role-picker before showing the password screen.

    Returns an empty list (with the same email echoed back) for unknown
    emails, to prevent enumeration. The frontend treats empty list as
    "no roles available — please check your email."
    """
    user = await get_user_by_email_with_roles(db, payload.email)
    if user is None or not user.is_active:
        return RolesForEmailResponse(email=payload.email, roles=[])
    roles = sorted({ra.role.value for ra in user.role_assignments})
    return RolesForEmailResponse(email=payload.email, roles=roles)


@router.get("/me", response_model=UserResponse)
async def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Return the authenticated user's profile. Requires a valid JWT."""
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value,
        is_active=current_user.is_active,
    )
