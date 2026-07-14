"""ChunkStore seam — psycopg is confined to PostgresChunkStore."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ledgerlens.ingestion.models import ChunkRecord
from ledgerlens.retrieval.models import ScoredChunk

# Provenance columns allowed as metadata filters (ADR-0001 single-Postgres payoff).
ALLOWED_FILTER_KEYS = frozenset({"ticker", "form_type", "fiscal_period"})


class ChunkStore(ABC):
    @abstractmethod
    def init_schema(self) -> None:
        """Create tables and indexes (idempotent)."""

    @abstractmethod
    def upsert_chunks(
        self,
        records: list[ChunkRecord],
        embeddings: dict[str, list[float]],
    ) -> None:
        """Insert or update chunk rows. Parents get NULL embedding."""

    @abstractmethod
    def count_rows(self) -> int:
        """Total rows in the chunks table."""

    @abstractmethod
    def count_embedded(self) -> int:
        """Rows with a non-NULL embedding (child + table targets)."""

    @abstractmethod
    def count_by_type(self) -> dict[str, int]:
        """Row counts keyed by chunk_type."""

    @abstractmethod
    def count_parents_embedded(self) -> int:
        """Parent rows that incorrectly have an embedding (should be 0)."""

    @abstractmethod
    def clear(self) -> None:
        """Delete all rows (used by embed_and_store --truncate before reload)."""

    @abstractmethod
    def search_dense(
        self,
        query_embedding: list[float],
        k: int,
        filters: dict[str, str] | None = None,
    ) -> list[ScoredChunk]:
        """pgvector cosine ANN over rows with non-NULL embedding (child + table)."""

    @abstractmethod
    def search_fts(
        self,
        query_text: str,
        k: int,
        filters: dict[str, str] | None = None,
    ) -> list[ScoredChunk]:
        """Sparse FTS over embedded units only (``embedding IS NOT NULL``)."""

    @abstractmethod
    def fetch_parent(self, parent_id: str) -> ChunkRecord | None:
        """Fetch a parent section by id (Phase 4 synthesis expansion)."""


def validate_filters(filters: dict[str, str] | None) -> dict[str, str]:
    if not filters:
        return {}
    unknown = set(filters) - ALLOWED_FILTER_KEYS
    if unknown:
        raise ValueError(
            f"Unsupported filter key(s): {sorted(unknown)}. "
            f"Allowed: {sorted(ALLOWED_FILTER_KEYS)}"
        )
    return dict(filters)


def row_matches_filters(row: dict, filters: dict[str, str]) -> bool:
    return all(row.get(key) == value for key, value in filters.items())
