"""Runtime configuration.

Settings are intentionally cheap to construct and do not connect to any external
service.  This keeps startup and ``GET /health`` safe when optional credentials or
local infrastructure are absent.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # The repository's documented deployment uses PostgreSQL.  A test can use an
    # aiosqlite URL, while no connection is attempted until a query is submitted.
    database_url: str = "postgresql+asyncpg://crosscheck:crosscheck@localhost:5432/crosscheck"
    redis_url: str = "redis://localhost:6379/0"

    # OpenAI and DeepSeek are the first production comparison pair.  A caller can
    # still select ``deterministic`` explicitly for local/offline fixtures.
    crosscheck_models: str = Field(default="gpt-4o-mini,deepseek-chat", alias="CROSSCHECK_MODELS")
    allowed_models: str | None = Field(default=None, alias="CROSSCHECK_ALLOWED_MODELS")

    prompt_version: str = "unified-v1"
    query_deadline_seconds: float = Field(default=20.0, gt=0.0, le=120.0)
    max_question_length: int = Field(default=10_000, gt=0, le=100_000)
    max_body_bytes: int = Field(default=1_000_000, gt=0, le=10_000_000)
    max_raw_response_chars: int = Field(default=120_000, gt=0, le=1_000_000)

    # The adapter keys are loaded but never persisted or included in prompts.
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    tavily_api_key: str | None = None

    cache_ttl_seconds: int = Field(default=86_400, gt=0)

    @field_validator("crosscheck_models", "allowed_models", mode="before")
    @classmethod
    def normalize_model_env(cls, value: object) -> object:
        if value is None:
            return value
        if isinstance(value, (list, tuple, set)):
            return ",".join(str(item) for item in value)
        return str(value)

    def configured_models(self) -> list[str]:
        """Return configured model identifiers in stable order without duplicates."""

        raw = self.allowed_models if self.allowed_models and self.allowed_models.strip() else self.crosscheck_models
        names: list[str] = []
        seen: set[str] = set()
        for item in raw.split(","):
            name = item.strip()
            if name and name not in seen:
                names.append(name)
                seen.add(name)
        return names


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
