"""Runtime configuration.

Settings are intentionally cheap to construct and do not connect to any external
service.  This keeps startup and ``GET /health`` safe when optional credentials or
local infrastructure are absent.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
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
    # Provider attempt/retry controls.  An attempt is capped at ten seconds by
    # default and all attempts share the absolute query deadline.
    adapter_attempt_timeout_seconds: float = Field(default=10.0, gt=0.0, le=120.0)
    adapter_max_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_base_seconds: float = Field(default=0.25, ge=0.0, le=30.0)
    retry_backoff_max_seconds: float = Field(default=5.0, ge=0.0, le=120.0)
    retry_jitter_seconds: float = Field(default=0.25, ge=0.0, le=30.0)
    retry_after_max_seconds: float = Field(default=5.0, ge=0.0, le=120.0)
    # The limit is optional to preserve the safe local tracer behavior.  When
    # supplied, estimates/reported costs are treated as a guard, not a billing
    # guarantee.
    max_query_cost_usd: float | None = Field(default=None, ge=0.0, le=1_000_000.0)
    model_cost_estimates: dict[str, float] = Field(default_factory=dict)
    max_question_length: int = Field(default=10_000, gt=0, le=100_000)
    max_body_bytes: int = Field(default=1_000_000, gt=0, le=10_000_000)
    max_raw_response_chars: int = Field(default=120_000, gt=0, le=1_000_000)
    max_constraints_length: int = Field(default=10_000, gt=0, le=100_000)
    max_model_count: int = Field(default=8, gt=0, le=100)
    max_model_name_length: int = Field(default=200, gt=0, le=2_000)

    # Anonymous public-flow controls.  These are intentionally process-local for
    # the MVP; deployments with multiple workers should put an edge limiter in
    # front of the service as well.
    rate_limit_requests: int = Field(default=60, gt=0, le=100_000)
    rate_limit_window_seconds: float = Field(default=60.0, gt=0.0, le=86_400.0)
    max_concurrent_queries: int = Field(default=8, gt=0, le=10_000)
    trusted_proxy_ips: str = ""
    # ``trusted_proxies`` is retained as a friendly constructor/env alias used by
    # deployment manifests; both forms are normalized by ``trusted_proxy_tokens``.
    trusted_proxies: str | list[str] | None = None
    max_feedback_comment_length: int = Field(default=5_000, gt=0, le=100_000)
    max_feedback_answer_length: int = Field(default=20_000, gt=0, le=200_000)
    max_evidence_count: int = Field(default=100, gt=0, le=1_000)
    max_evidence_snippet_chars: int = Field(default=4_000, gt=0, le=100_000)

    # The adapter keys are loaded but never persisted or included in prompts.
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    tavily_api_key: str | None = None

    cache_ttl_seconds: int = Field(default=86_400, gt=0)

    @model_validator(mode="after")
    def validate_retry_bounds(self) -> "Settings":
        if self.retry_backoff_max_seconds < self.retry_backoff_base_seconds:
            raise ValueError("retry_backoff_max_seconds must be >= retry_backoff_base_seconds")
        return self

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

    def trusted_proxy_tokens(self) -> list[str]:
        """Return configured trusted proxy IPs/CIDRs in stable order."""

        values: list[str] = []
        raw_values: list[str] = [self.trusted_proxy_ips]
        if isinstance(self.trusted_proxies, list):
            raw_values.extend(str(item) for item in self.trusted_proxies)
        elif self.trusted_proxies:
            raw_values.append(self.trusted_proxies)
        for raw in raw_values:
            values.extend(item.strip() for item in raw.split(",") if item.strip())
        return values


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
