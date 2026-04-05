"""Pydantic Settings loaded from .env — single source of truth for all configuration."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "XProject API"
    debug: bool = False
    secret_key: str = "changeme-in-production-use-256-bit-random"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    database_url: str = "postgresql+asyncpg://xproject:xproject@db:5432/xproject"
    redis_url: str = "redis://redis:6379"

    slesh_api_url: str = ""
    slesh_api_key: str = ""

    anthropic_api_key: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
