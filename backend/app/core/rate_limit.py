"""Token-bucket rate limiting via slowapi (FastAPI wrapper around limits).

Why this exists:
    Without rate limits, a stuck client retry loop, a malicious user, or
    a bug in our own frontend can trivially DoS the system:
      - Holding Send → thousands of /messages POSTs
      - Drag-uploading 1000 files → flood /attachments/presign
      - Search-as-you-type bug → /search hammered every keystroke

    Rate limits are per-user (via JWT subject), tracked in Redis so they
    survive backend restarts and work across multiple backend instances.

    Limits live in settings (rate_limit_messages, _uploads, _search) so
    they're tunable without code changes.

Usage in routers:

    from app.core.rate_limit import limiter, key_user

    @router.post("/foo")
    @limiter.limit(f"{settings.rate_limit_messages}/minute", key_func=key_user)
    async def foo(request: Request, ...):
        ...

The `request: Request` parameter is REQUIRED for slowapi to inspect
headers; FastAPI injects it automatically.
"""
from __future__ import annotations

from fastapi import HTTPException, Request, status
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings


def key_user(request: Request) -> str:
    """Per-user rate-limit key derived from the JWT subject (user_id).

    Falls back to client IP if the request is unauthenticated (login,
    health checks). This way unauthenticated endpoints still get
    abuse protection.

    Note: we read the Authorization header directly here instead of going
    through the get_current_user dependency, because slowapi runs BEFORE
    the dependency injection layer.
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
        try:
            from app.core.security import decode_access_token
            payload = decode_access_token(token)
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:                                    # noqa: BLE001
            pass                                             # fall through to IP
    return f"ip:{get_remote_address(request)}"


# Single limiter instance shared by all routers.
# storage_uri uses Redis so limits are shared across backend instances.
limiter = Limiter(
    key_func=key_user,
    storage_uri=settings.redis_url,
    headers_enabled=True,                                    # adds X-RateLimit-* headers
)


async def rate_limit_exceeded_handler(
    request: Request,
    exc: RateLimitExceeded,
) -> None:
    """Translate slowapi's exception into a clean HTTP 429 response.

    Wired up in main.py via app.add_exception_handler.
    """
    raise HTTPException(
        status_code = status.HTTP_429_TOO_MANY_REQUESTS,
        detail      = f"Rate limit exceeded: {exc.detail}. Slow down and try again.",
    )
