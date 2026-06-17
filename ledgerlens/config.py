"""Single source of truth for configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MVP_TICKERS: list[str] = [
    "MSFT",
    "AAPL",
    "GOOGL",
    "META",
    "NVDA",
    "ADBE",
    "CRM",
    "ORCL",
    "NOW",
    "INTU",
    "WDAY",
    "SNOW",
    "DDOG",
    "CRWD",
    "PANW",
    "MDB",
    "AMD",
    "AVGO",
]

VALIDATE_FIRST_TICKERS: list[str] = ["MSFT", "SNOW", "NVDA"]


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
    filing_source: str = "edgar"

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

    # Phase 1 — ingestion & chunking
    tickers: list[str] = Field(default_factory=lambda: list(MVP_TICKERS))
    edgar_identity: str | None = None
    form_types: list[str] = Field(default_factory=lambda: ["10-K"])
    child_target_tokens: int = Field(default=400, ge=1)
    child_max_tokens: int = Field(default=500, ge=1)
    child_hard_max_tokens: int = Field(default=800, ge=1)
    child_overlap_tokens: int = Field(default=0, ge=0, le=100)
    processed_dir: Path = Path("data/processed")
    sample_path: Path = Path("data/samples/chunks_sample.jsonl")
    fixture_path: Path = Path("data/fixtures/fake_filing.json")

    @property
    def chunks_path(self) -> Path:
        return self.processed_dir / "chunks.jsonl"

    @property
    def quality_report_path(self) -> Path:
        return self.processed_dir / "quality_report.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
