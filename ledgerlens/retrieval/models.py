"""Retrieval result types — provenance travels with every hit."""

from __future__ import annotations

from dataclasses import dataclass

from ledgerlens.ingestion.models import ChunkRecord


@dataclass(frozen=True)
class ScoredChunk:
    """One hit from a single retrieval leg (dense or FTS)."""

    chunk: ChunkRecord
    score: float


@dataclass(frozen=True)
class RetrievalResult:
    """Final ranked hit after fusion (and optional rerank)."""

    chunk: ChunkRecord
    rank: int
    score: float
    rrf_score: float
    dense_score: float | None = None
    fts_score: float | None = None
    rerank_score: float | None = None
