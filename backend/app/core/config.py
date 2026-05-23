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
    anthropic_api_key: str = ""

    # Slesh POS Integration — read-only adapter; production-only (no sandbox)
    slesh_base_url:        str = "https://api.slesh.it/api"
    slesh_api_token:       str = ""    # set via env (.env), 1-year lifetime
    slesh_brand_id:        str = ""    # set via env (.env), 24-char hex
    slesh_request_timeout: float = 10.0    # seconds — single HTTP call ceiling
    slesh_rate_limit_rps:  int = 5         # client-side limiter, tune later
    slesh_max_retries:     int = 3         # exp backoff: 1s -> 2s -> 4s

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
        extra             = "ignore"  # tolerate undeclared .env keys


settings = Settings()
