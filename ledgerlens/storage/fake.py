"""In-memory ChunkStore for offline tests and fake-backend runs."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from ledgerlens.config import Settings
from ledgerlens.ingestion.models import ChunkRecord, ChunkType
from ledgerlens.retrieval.models import ScoredChunk
from ledgerlens.storage.row_mapper import chunk_record_from_row
from ledgerlens.storage.store import ChunkStore, row_matches_filters, validate_filters


def _row_from_record(
    record: ChunkRecord,
    embedding: list[float] | None,
) -> dict[str, Any]:
    prov = record.provenance
    return {
        "id": record.id,
        "chunk_type": record.chunk_type,
        "text": record.text,
        "parent_id": record.parent_id,
        "is_table": record.is_table,
        "token_count": record.token_count,
        "summary": record.summary,
        "table_data": record.table_data,
        "company": prov.company,
        "ticker": prov.ticker,
        "cik": prov.cik,
        "form_type": prov.form_type,
        "fiscal_period": prov.fiscal_period,
        "section": prov.section,
        "accession_no": prov.accession_no,
        "source_url": prov.source_url,
        "char_start": prov.char_start,
        "char_end": prov.char_end,
        "embedding": embedding,
    }


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Match pgvector ``<=>`` cosine distance: ``1 - cosine_similarity``."""
    if len(a) != len(b):
        raise ValueError(f"Embedding length mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    return 1.0 - (dot / (norm_a * norm_b))


def _fts_terms(query_text: str) -> list[str]:
    """Tokenize a query for OR-style FTS (mirrors Postgres to_tsvector lexemes).

    Stopwords and 1-char tokens are dropped so NL questions still match on
    content words (any-term OR), rather than requiring every word to appear.
    """
    raw = [t for t in re.findall(r"[A-Za-z0-9_]+", query_text.lower()) if len(t) > 1]
    return [t for t in raw if t not in _FTS_STOPWORDS]


# Minimal English stopword set — enough to mirror to_tsvector dropping "what/are/is".
_FTS_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "what",
        "which",
        "who",
        "with",
    }
)


def _fts_score(text: str, terms: list[str]) -> float:
    """OR match: at least one term must hit; score = fraction of terms present."""
    if not terms:
        return 0.0
    haystack = text.lower()
    hits = sum(1 for term in terms if term in haystack)
    if hits == 0:
        return 0.0
    return hits / len(terms)


def _is_rankable(row: dict[str, Any]) -> bool:
    chunk_type = row["chunk_type"]
    if isinstance(chunk_type, ChunkType):
        return chunk_type in (ChunkType.CHILD, ChunkType.TABLE)
    return chunk_type in (ChunkType.CHILD.value, ChunkType.TABLE.value)


class FakeChunkStore(ChunkStore):
    def __init__(self, settings: Settings | None = None) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    def init_schema(self) -> None:
        return None

    def upsert_chunks(
        self,
        records: list[ChunkRecord],
        embeddings: dict[str, list[float]],
    ) -> None:
        parents = [r for r in records if r.chunk_type == ChunkType.PARENT]
        others = [r for r in records if r.chunk_type != ChunkType.PARENT]
        for record in parents + others:
            emb = embeddings.get(record.id)
            if record.chunk_type == ChunkType.PARENT:
                emb = None
            self._rows[record.id] = _row_from_record(record, emb)

    def count_rows(self) -> int:
        return len(self._rows)

    def count_embedded(self) -> int:
        return sum(1 for row in self._rows.values() if row["embedding"] is not None)

    def count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self._rows.values():
            chunk_type = row["chunk_type"]
            key = str(chunk_type)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def count_parents_embedded(self) -> int:
        return sum(
            1
            for row in self._rows.values()
            if row["chunk_type"] == ChunkType.PARENT and row["embedding"] is not None
        )

    def clear(self) -> None:
        self._rows.clear()

    def get_row(self, chunk_id: str) -> dict[str, Any] | None:
        row = self._rows.get(chunk_id)
        if row is None:
            return None
        return json.loads(json.dumps(row))

    def search_dense(
        self,
        query_embedding: list[float],
        k: int,
        filters: dict[str, str] | None = None,
    ) -> list[ScoredChunk]:
        filters = validate_filters(filters)
        scored: list[tuple[float, str, dict[str, Any]]] = []
        for chunk_id, row in self._rows.items():
            if row["embedding"] is None:
                continue
            if not _is_rankable(row):
                continue
            if filters and not row_matches_filters(row, filters):
                continue
            distance = _cosine_distance(query_embedding, row["embedding"])
            scored.append((distance, chunk_id, row))

        scored.sort(key=lambda item: (item[0], item[1]))
        return [
            ScoredChunk(chunk=chunk_record_from_row(row), score=distance)
            for distance, _chunk_id, row in scored[:k]
        ]

    def search_fts(
        self,
        query_text: str,
        k: int,
        filters: dict[str, str] | None = None,
    ) -> list[ScoredChunk]:
        filters = validate_filters(filters)
        terms = _fts_terms(query_text)
        scored: list[tuple[float, str, dict[str, Any]]] = []
        for chunk_id, row in self._rows.items():
            # Embedded units only — mirrors Postgres `embedding IS NOT NULL`
            # so 50k-char parents never pollute FTS → RRF.
            if row["embedding"] is None:
                continue
            if filters and not row_matches_filters(row, filters):
                continue
            score = _fts_score(row["text"], terms)
            if score <= 0.0:
                continue
            scored.append((score, chunk_id, row))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            ScoredChunk(chunk=chunk_record_from_row(row), score=score)
            for score, _chunk_id, row in scored[:k]
        ]

    def fetch_parent(self, parent_id: str) -> ChunkRecord | None:
        row = self._rows.get(parent_id)
        if row is None:
            return None
        if row["chunk_type"] != ChunkType.PARENT and row["chunk_type"] != ChunkType.PARENT.value:
            return None
        return chunk_record_from_row(row)
