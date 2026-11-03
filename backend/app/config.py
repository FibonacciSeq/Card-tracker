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
    # Migrations need the schema owner; the runtime API should use a
    # non-owner role so Postgres RLS is enforced. When unset (local SQLite and
    # tests), migrations use database_url.
    migration_database_url: str | None = None
    jwt_secret: str = "dev-only-change-me"
    jwt_issuer: str = "cardtracker-platform"
    access_token_minutes: int = 60
    # Customer accounts are memory-only in the app. The server expiry still
    # bounds a session that stays open in the background.
    customer_access_token_minutes: int = 720
    customer_refresh_token_minutes: int = 10080
    otp_expiry_seconds: int = 600
    otp_resend_seconds: int = 60
    otp_max_attempts: int = 5
    otp_request_ip_limit: int = 10
    otp_request_ip_window_seconds: int = 3600
    otp_request_email_limit: int = 5
    otp_request_email_window_seconds: int = 900
    otp_verify_ip_limit: int = 20
    otp_verify_ip_window_seconds: int = 900
    otp_verify_email_limit: int = 10
    otp_verify_email_window_seconds: int = 900
    otp_email_max_attempts: int = 5
    # Empty falls back to jwt_secret, so existing deployments need no new secret.
    otp_secret: str = ""
    otp_debug_code: bool = False
    default_hold_hours: int = 24
    # Production must use `alembic upgrade head`; only local SQLite runs enable
    # auto-create explicitly.
    auto_create_tables: bool = False
    cors_origins: str = "*"
    # Public base URL used in customer emails (unsubscribe pages). Set this to
    # the externally reachable API origin in production.
    public_api_url: str = "http://localhost:8000"
    # Canonical app host used for public customer deep links and QR codes.
    # The app still accepts the legacy custom-scheme fallback when needed.
    public_app_url: str = "https://app.cardtracker.local"
    # Optional dedicated key for signed unsubscribe links. Falls back to the
    # JWT secret so existing deployments keep working without new config.
    unsubscribe_secret: str = ""
    min_app_version: str = "0.1.0"
    # In-process sliding windows; move to Redis when the API runs multiple
    # workers. Generous enough to never bother a person, tight enough to stop
    # scripted password guessing and reservation spam.
    login_rate_limit: int = 10
    login_rate_window_seconds: int = 300
    reservation_rate_limit: int = 30
    reservation_rate_window_seconds: int = 3600
    restock_alert_rate_limit: int = 20
    restock_alert_rate_window_seconds: int = 3600
    card_request_rate_limit: int = 10
    card_request_rate_window_seconds: int = 3600
    # Notification delivery. "console" logs messages (useful in development);
    # "smtp" sends real email; "none" disables delivery entirely.
    notification_backend: str = "console"
    notification_max_attempts: int = 8
    # Push delivery: "console" logs only the platform, "native" uses FCM/APNs,
    # and "none" leaves push rows queued for a later worker run.
    push_backend: str = "console"
    push_timeout_seconds: float = 10.0
    fcm_project_id: str = ""
    fcm_credentials_file: str = ""
    apns_team_id: str = ""
    apns_key_id: str = ""
    apns_private_key_file: str = ""
    apns_bundle_id: str = ""
    apns_use_sandbox: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@cardtracker.local"
    smtp_starttls: bool = True

    @model_validator(mode="after")
    def _validate_jwt_secret(self) -> "Settings":
        if self.environment not in ("development", "test") and len(self.jwt_secret) < 32:
            raise ValueError("CARDTRACKER_JWT_SECRET must be at least 32 characters outside development")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
