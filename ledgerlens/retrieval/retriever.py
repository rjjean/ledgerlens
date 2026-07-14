"""Hybrid retriever: query embed → FTS + dense → RRF → optional MiniLM rerank."""

from __future__ import annotations

from dataclasses import dataclass

from ledgerlens.config import Settings, get_settings
from ledgerlens.ingestion.models import ChunkRecord
from ledgerlens.interfaces.embedder import Embedder
from ledgerlens.interfaces.factory import get_embedder, get_reranker
from ledgerlens.interfaces.reranker import Reranker
from ledgerlens.retrieval.entities import resolve_ticker
from ledgerlens.retrieval.fusion import reciprocal_rank_fusion
from ledgerlens.retrieval.models import RetrievalResult, ScoredChunk
from ledgerlens.retrieval.text import rerank_text_for_chunk
from ledgerlens.storage.factory import get_chunk_store
from ledgerlens.storage.store import ChunkStore


@dataclass(frozen=True)
class LegStats:
    """Per-query hybrid leg sizes — used by eval to catch a dead FTS/dense leg."""

    dense_count: int
    fts_count: int
    overlap_count: int
    resolved_ticker: str | None = None
    ticker_filter_applied: bool = False


class HybridRetriever:
    def __init__(
        self,
        settings: Settings | None = None,
        store: ChunkStore | None = None,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._store = store or get_chunk_store()
        self._embedder = embedder or get_embedder()
        self._reranker = reranker or get_reranker()

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, str] | None = None,
        *,
        rerank_enabled: bool | None = None,
        ticker_filter_enabled: bool | None = None,
    ) -> list[RetrievalResult]:
        results, _stats = self.retrieve_with_stats(
            query,
            top_k=top_k,
            filters=filters,
            rerank_enabled=rerank_enabled,
            ticker_filter_enabled=ticker_filter_enabled,
        )
        return results

    def retrieve_with_stats(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, str] | None = None,
        *,
        rerank_enabled: bool | None = None,
        ticker_filter_enabled: bool | None = None,
    ) -> tuple[list[RetrievalResult], LegStats]:
        settings = self._settings
        final_k = top_k if top_k is not None else settings.retrieval_top_k
        do_rerank = settings.rerank_enabled if rerank_enabled is None else rerank_enabled
        do_ticker_filter = (
            settings.ticker_filter_enabled
            if ticker_filter_enabled is None
            else ticker_filter_enabled
        )

        resolved: str | None = None
        effective_filters = filters
        ticker_filter_applied = False
        # Explicit caller filters always win — never override them.
        if filters is None and do_ticker_filter:
            resolved = resolve_ticker(query)
            if resolved is not None:
                effective_filters = {"ticker": resolved}
                ticker_filter_applied = True
        elif filters is None:
            resolved = resolve_ticker(query)

        query_vec = self._embedder.embed_query(query)
        dense = self._store.search_dense(
            query_vec, settings.dense_candidates, effective_filters
        )
        fts = self._store.search_fts(query, settings.fts_candidates, effective_filters)

        dense_ids = {hit.chunk.id for hit in dense}
        fts_ids = {hit.chunk.id for hit in fts}
        stats = LegStats(
            dense_count=len(dense),
            fts_count=len(fts),
            overlap_count=len(dense_ids & fts_ids),
            resolved_ticker=resolved,
            ticker_filter_applied=ticker_filter_applied,
        )

        by_id, dense_scores, fts_scores = _index_leg_hits(dense, fts)
        fused = reciprocal_rank_fusion(
            [
                [hit.chunk.id for hit in dense],
                [hit.chunk.id for hit in fts],
            ],
            k=settings.rrf_k,
        )
        if not fused:
            return [], stats

        candidates = fused[: settings.rerank_candidates]
        if do_rerank:
            ordered_ids, final_scores, rerank_scores = self._rerank_candidates(
                query, candidates, by_id, final_k
            )
        else:
            ordered_ids = [chunk_id for chunk_id, _ in candidates[:final_k]]
            final_scores = {chunk_id: score for chunk_id, score in candidates[:final_k]}
            rerank_scores: dict[str, float] = {}

        rrf_by_id = dict(fused)
        results: list[RetrievalResult] = []
        for rank, chunk_id in enumerate(ordered_ids, start=1):
            chunk = by_id[chunk_id]
            results.append(
                RetrievalResult(
                    chunk=chunk,
                    rank=rank,
                    score=final_scores[chunk_id],
                    rrf_score=rrf_by_id[chunk_id],
                    dense_score=dense_scores.get(chunk_id),
                    fts_score=fts_scores.get(chunk_id),
                    rerank_score=rerank_scores.get(chunk_id),
                )
            )
        return results, stats

    def _rerank_candidates(
        self,
        query: str,
        candidates: list[tuple[str, float]],
        by_id: dict[str, ChunkRecord],
        top_k: int,
    ) -> tuple[list[str], dict[str, float], dict[str, float]]:
        candidate_ids = [chunk_id for chunk_id, _ in candidates]
        texts = [rerank_text_for_chunk(by_id[chunk_id]) for chunk_id in candidate_ids]
        ranked = self._reranker.rerank(query, texts, top_k)
        ordered_ids = [candidate_ids[item.index] for item in ranked]
        scores = {candidate_ids[item.index]: item.score for item in ranked}
        return ordered_ids, scores, scores


def _index_leg_hits(
    dense: list[ScoredChunk],
    fts: list[ScoredChunk],
) -> tuple[dict[str, ChunkRecord], dict[str, float], dict[str, float]]:
    by_id: dict[str, ChunkRecord] = {}
    dense_scores: dict[str, float] = {}
    fts_scores: dict[str, float] = {}
    for hit in dense:
        by_id[hit.chunk.id] = hit.chunk
        dense_scores[hit.chunk.id] = hit.score
    for hit in fts:
        by_id[hit.chunk.id] = hit.chunk
        fts_scores[hit.chunk.id] = hit.score
    return by_id, dense_scores, fts_scores
