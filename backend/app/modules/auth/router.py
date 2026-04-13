"""HTTP router for the auth module.

Endpoints:
  POST /auth/login   — exchange email + password for a JWT access token
  GET  /auth/me      — return the current authenticated user (requires JWT)
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.modules.auth.models import User
from app.modules.auth.schemas import TokenResponse, UserResponse
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
    if user is None:
        raise credentials_exc
    return user


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db:        Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Exchange email (sent as 'username' per OAuth2 spec) and password for a JWT.

    Returns 401 on invalid credentials. Same response for unknown email and wrong
    password (prevents user enumeration attacks).
    """
    service = AuthService(db)
    user = await service.authenticate_user(form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = service.create_user_token(user)
    return TokenResponse(access_token=token, token_type="bearer")


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
