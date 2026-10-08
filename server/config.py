"""Application settings and environment configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server runtime
    HOST: str = Field(default="0.0.0.0", description="Bind host")
    PORT: int = Field(default=8000, description="Bind port")
    DEBUG: bool = Field(default=False, description="Debug mode")

    # Notifier selection
    NOTIFIER_TYPE: str = Field(
        default="console",
        description="Notifier backend: console, fcm, lan, multi"
    )

    # Storage backend
    STORE_TYPE: str = Field(
        default="memory",
        description="Pairing storage backend: memory, sqlite, firestore"
    )
    SQLITE_PATH: str = Field(
        default="notifs.db",
        description="Path to SQLite database file"
    )

    # Firebase credentials (used in Phase 5+)
    GOOGLE_APPLICATION_CREDENTIALS: str | None = Field(
        default="server/service-account.json",
        description="Path to Firebase service account JSON",
    )
    TEST_FCM_TOKEN: str | None = Field(
        default=None,
        description="Static device token for dev testing",
    )
    FCM_TOKEN: str | None = Field(
        default=None,
        description="Alias for TEST_FCM_TOKEN",
    )

    @property
    def target_fcm_token(self) -> str | None:
        """Returns the configured FCM token (checking TEST_FCM_TOKEN or FCM_TOKEN)."""
        return self.FCM_TOKEN or self.TEST_FCM_TOKEN


settings = Settings()
