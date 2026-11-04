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
    # Content pipeline. The gateway is OpenAI-compatible; base_url lets a
    # deployment point at any compatible endpoint.
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_chunk_chars: int = Field(default=8000, ge=500)
    llm_timeout_seconds: float = Field(default=120.0, gt=0)
    max_source_chars: int = Field(default=200_000, ge=1000)
    max_pdf_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)
    max_url_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    url_timeout_seconds: float = Field(default=15.0, gt=0)
    url_max_redirects: int = Field(default=3, ge=0, le=10)
    max_job_items: int = Field(default=50, ge=1, le=500)
    worker_poll_seconds: float = Field(default=2.0, gt=0)
    worker_heartbeat_seconds: float = Field(default=30.0, gt=0)
    worker_stale_seconds: float = Field(default=300.0, gt=0)
    worker_max_attempts: int = Field(default=3, ge=1)
    app_timezone: str = "Asia/Ho_Chi_Minh"

    @field_validator("app_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        # ZoneInfo raises for unknown names, so a typo fails at startup
        # instead of silently shifting every due date.
        ZoneInfo(value)
        return value

    @field_validator("llm_base_url")
    @classmethod
    def _strip_llm_slash(cls, value: str) -> str:
        # The openai SDK appends "/chat/completions" itself.
        return value.rstrip("/")

    @field_validator("app_origin")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        # Browsers send Origin without a trailing slash; a configured value
        # with one would reject every write request.
        return value.rstrip("/")
