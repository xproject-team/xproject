"""Pydantic v2 request/response schemas for the auth module."""
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str  # owner | manager | bartender | warehouse


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str  # OAuth2PasswordRequestForm uses 'username' for the email field
    password: str



class RolesForEmailRequest(BaseModel):
    """Step 1 of the two-step login flow: user enters email, we return roles."""
    email: EmailStr


class RolesForEmailResponse(BaseModel):
    """The list of roles the given email is authorized for.

    Empty list = email exists but has no roles (shouldn't happen post-1A backfill)
    OR email doesn't exist (we don't distinguish, to prevent enumeration).
    """
    email: str
    roles: list[str]  # ["owner"], ["manager", "bartender"], etc.
