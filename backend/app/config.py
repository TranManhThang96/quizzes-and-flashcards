from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field is read from a QUIZZ_* env variable."""

    model_config = SettingsConfigDict(env_prefix="QUIZZ_")

    database_url: str
    app_origin: str = "https://quizz.thangtm.io.vn"
    environment: Literal["dev", "prod"] = "dev"
    cookie_secure: bool = True
    session_ttl_days: int = Field(default=30, ge=1)
    login_max_failures: int = Field(default=5, ge=1)
    login_window_minutes: int = Field(default=15, ge=1)
    app_timezone: str = "Asia/Ho_Chi_Minh"

    @field_validator("app_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        # ZoneInfo raises for unknown names, so a typo fails at startup
        # instead of silently shifting every due date.
        ZoneInfo(value)
        return value

    @field_validator("app_origin")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        # Browsers send Origin without a trailing slash; a configured value
        # with one would reject every write request.
        return value.rstrip("/")
