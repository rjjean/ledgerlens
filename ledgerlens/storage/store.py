"""ChunkStore seam — psycopg is confined to PostgresChunkStore."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ledgerlens.ingestion.models import ChunkRecord


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
