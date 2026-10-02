from functools import lru_cache

from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    firebase_project_id: str | None = Field(default=None, alias="FIREBASE_PROJECT_ID")
    firebase_client_email: str | None = Field(default=None, alias="FIREBASE_CLIENT_EMAIL")
    firebase_private_key: str | None = Field(default=None, alias="FIREBASE_PRIVATE_KEY", repr=False, exclude=True)
    frontend_url: str | None = Field(default=None, alias="FRONTEND_URL")
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY", repr=False, exclude=True)
    # A session counts as "active" if it is open and was seen within this window.
    session_active_window_seconds: int = Field(default=300, ge=30, le=86400, alias="SESSION_ACTIVE_WINDOW_SECONDS")
    # "Recently active" users: any session seen within this (longer) window, open or not.
    session_recent_window_seconds: int = Field(default=86400, ge=60, le=2592000, alias="SESSION_RECENT_WINDOW_SECONDS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    @field_validator(
        "firebase_project_id",
        "firebase_client_email",
        "firebase_private_key",
        "frontend_url",
        "groq_api_key",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("frontend_url")
    @classmethod
    def _valid_origins(cls, value):
        for origin in (value or "").split(","):
            origin = origin.strip().rstrip("/")
            if not origin or origin == "*":
                continue  # wildcard remains disabled by cors_origins
            parsed = urlsplit(origin)
            if (parsed.scheme not in ("http", "https") or not parsed.hostname
                    or parsed.username or parsed.password or parsed.path
                    or parsed.query or parsed.fragment or "*" in origin):
                raise ValueError("FRONTEND_URL must contain only HTTP(S) origins, without paths or credentials.")
            try:
                parsed.port
            except ValueError:
                raise ValueError("FRONTEND_URL contains an invalid port.") from None
        return value

    @property
    def cors_origins(self) -> list[str]:
        if not self.frontend_url:
            return []

        origins = [
            origin.strip().rstrip("/")
            for origin in self.frontend_url.split(",")
            if origin.strip()
        ]
        return [origin for origin in origins if origin != "*"]

    @property
    def firebase_private_key_normalized(self) -> str | None:
        if not self.firebase_private_key:
            return None
        key = self.firebase_private_key.strip().strip('"').strip("'")
        return key.replace("\\n", "\n")


@lru_cache
def get_settings() -> Settings:
    return Settings()



