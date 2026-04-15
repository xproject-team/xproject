"""Pydantic Settings — single source of truth for all runtime configuration.

All values can be overridden by environment variables of the same name
(case-insensitive). For local development, set them in /.env at the
project root (resolved via absolute path so it works regardless of CWD).

Hostname defaults assume LOCAL development (host machine running uvicorn).
Docker compose overrides them with container-network hostnames via env vars.
"""
from pathlib import Path

from pydantic_settings import BaseSettings


# Resolve .env to project root (parent of backend/) regardless of CWD.
# Fixes the bug where running uvicorn from different directories caused
# settings to silently miss the .env file.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ENV_FILE     = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    app_name: str  = "XProject API"
    debug:    bool = False

    # Auth
    secret_key:                  str = "changeme-in-production-use-256-bit-random"
    algorithm:                   str = "HS256"
    access_token_expire_minutes: int = 30

    # Infrastructure — defaults are LOCAL dev (override in Docker/prod)
    database_url: str = "postgresql+asyncpg://xproject:xproject@localhost:5432/xproject"
    redis_url:    str = "redis://localhost:6379"

    # External services
    slesh_api_url:     str = ""
    slesh_api_key:     str = ""
    anthropic_api_key: str = ""

    # CORS — comma-separated list of allowed origins (env: CORS_ORIGINS)
    cors_origins: str = "http://localhost:3000,http://localhost:5174"

    # Observability
    log_level: str  = "INFO"          # DEBUG | INFO | WARNING | ERROR
    log_sql:   bool = False           # set true only when debugging queries

    # Rate limits (per minute, per user) — used by Fix 5
    rate_limit_messages: int = 60
    rate_limit_uploads:  int = 20
    rate_limit_search:   int = 30

    class Config:
        env_file          = str(_ENV_FILE)
        env_file_encoding = "utf-8"
        case_sensitive    = False


settings = Settings()
