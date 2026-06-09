"""Single source of truth for configuration."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Backend selectors
    embedder_backend: str = "fake"
    reranker_backend: str = "fake"
    llm_backend: str = "fake"

    # Locked model IDs (design doc §6)
    embedder_model: str = "voyage-finance-2"
    embedder_dimensions: int = 1024
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    llm_model: str = "anthropic/claude-haiku-4-5"
    # Eval-only (Phase 7). Must be a different model family from the generator.
    judge_model: str = "REPLACE_WITH_JUDGE_MODEL"

    # Secrets (optional until real backends are used)
    database_url: str | None = None
    anthropic_api_key: str | None = None
    voyage_api_key: str | None = None

    max_output_tokens: int = Field(default=1024, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
