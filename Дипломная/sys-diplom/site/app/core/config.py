from secrets import token_urlsafe
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "Домашняя медкарта"
    database_url: str = "postgresql+psycopg://phr:phr@localhost:5432/phr"
    secret_key: str = Field(default_factory=lambda: token_urlsafe(48))
    access_token_expire_minutes: int = 1440
    allow_registration: bool = True
    session_cookie_secure: bool = True
    force_https_redirect: bool = True
    upload_dir: str = "uploads"
    max_upload_mb: int = 10
    backup_dir: str = "backups"
    auto_backup_enabled: bool = False
    auto_backup_interval_hours: int = 24
    backup_retention_days: int = 14
    notification_channel: str = "log"
    notification_retry_count: int = 2
    reminder_scheduler_enabled: bool = False
    reminder_scheduler_poll_seconds: int = 60
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    notification_from_email: str | None = None
    notification_to_email: str | None = None
    matrix_homeserver_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MATRIX_HOMESERVER_URL", "MATRIX_HOMESERVER"),
    )
    matrix_access_token: str | None = None
    matrix_bot_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MATRIX_BOT_ID", "MATRIX_BOT_USER_ID", "MATRIX_USER_ID"),
    )
    matrix_user_id: str | None = Field(default=None, validation_alias="MATRIX_USER_ID")
    matrix_room_id: str | None = None
    redis_url: str | None = None
    openfda_api_key: str | None = None
    medication_cache_ttl_hours: int = 24
    blood_pressure_sys_alert_threshold: int = 160
    blood_pressure_dia_alert_threshold: int = 100
    blood_sugar_alert_threshold: float = 10.0
    missed_data_check_hour: int = 20

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def upload_path(self) -> Path:
        return BASE_DIR / self.upload_dir

    @property
    def backup_path(self) -> Path:
        return BASE_DIR / self.backup_dir

    @property
    def matrix_homeserver(self) -> str | None:
        return self.matrix_homeserver_url


settings = Settings()
