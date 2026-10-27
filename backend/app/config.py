"""Runtime configuration for the platform API."""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CARDTRACKER_",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "sqlite+pysqlite:///./cardtracker_platform.db"
    jwt_secret: str = "dev-only-change-me"
    jwt_issuer: str = "cardtracker-platform"
    access_token_minutes: int = 60
    default_hold_hours: int = 24
    # Production must use `alembic upgrade head`; only local SQLite runs enable
    # auto-create explicitly.
    auto_create_tables: bool = False
    cors_origins: str = "*"
    min_app_version: str = "0.1.0"
    # In-process sliding windows; move to Redis when the API runs multiple
    # workers. Generous enough to never bother a person, tight enough to stop
    # scripted password guessing and reservation spam.
    login_rate_limit: int = 10
    login_rate_window_seconds: int = 300
    reservation_rate_limit: int = 30
    reservation_rate_window_seconds: int = 3600

    @model_validator(mode="after")
    def _validate_jwt_secret(self) -> "Settings":
        if self.environment not in ("development", "test") and len(self.jwt_secret) < 32:
            raise ValueError("CARDTRACKER_JWT_SECRET must be at least 32 characters outside development")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
