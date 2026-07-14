"""Hybrid retrieval — FTS + pgvector + RRF + rerank."""

from ledgerlens.retrieval.fusion import reciprocal_rank_fusion
from ledgerlens.retrieval.models import RetrievalResult, ScoredChunk

__all__ = [
    "HybridRetriever",
    "LegStats",
    "RetrievalResult",
    "ScoredChunk",
    "reciprocal_rank_fusion",
    "rerank_text_for_chunk",
    "resolve_ticker",
]


def __getattr__(name: str):
    # Lazy imports avoid circular load: storage.store → retrieval.models
    # while HybridRetriever imports ChunkStore.
    if name == "HybridRetriever":
        from ledgerlens.retrieval.retriever import HybridRetriever

        return HybridRetriever
    if name == "LegStats":
        from ledgerlens.retrieval.retriever import LegStats

        return LegStats
    if name == "rerank_text_for_chunk":
        from ledgerlens.retrieval.text import rerank_text_for_chunk

        return rerank_text_for_chunk
    if name == "resolve_ticker":
        from ledgerlens.retrieval.entities import resolve_ticker

        return resolve_ticker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
