"""Embed chunks and upsert into ChunkStore with reconciliation."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from ledgerlens.config import Settings, get_settings
from ledgerlens.ingestion.models import ChunkRecord, ChunkType
from ledgerlens.interfaces.embedder import Embedder
from ledgerlens.interfaces.factory import get_embedder
from ledgerlens.storage.factory import get_chunk_store
from ledgerlens.storage.store import ChunkStore

logger = logging.getLogger(__name__)


class ReconciliationError(Exception):
    """Raised when stored row counts do not match expected chunk counts."""


class StorageReport(BaseModel):
    total_chunks: int
    rows: int
    embedded: int
    expected_embedded: int
    parents_embedded: int
    by_type: dict[str, int] = Field(default_factory=dict)
    mismatches: list[str] = Field(default_factory=list)
    passed: bool = False


def load_chunks(path: Path) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            chunks.append(ChunkRecord.model_validate_json(line))
    return chunks


def filter_chunks_by_tickers(chunks: list[ChunkRecord], tickers: list[str]) -> list[ChunkRecord]:
    allowed = {t.upper() for t in tickers}
    return [c for c in chunks if c.provenance.ticker.upper() in allowed]


def is_embed_target(chunk: ChunkRecord) -> bool:
    return chunk.chunk_type in (ChunkType.CHILD, ChunkType.TABLE)


def embed_text_for_chunk(chunk: ChunkRecord) -> str:
    """Searchable text for embedding: child body or table linearized text (no summary)."""
    return chunk.text


def embed_targets(
    chunks: list[ChunkRecord],
    embedder: Embedder,
    settings: Settings,
) -> dict[str, list[float]]:
    targets = [c for c in chunks if is_embed_target(c)]
    embeddings: dict[str, list[float]] = {}
    batch_size = settings.embed_batch_size
    total_batches = (len(targets) + batch_size - 1) // batch_size if targets else 0

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        batch = targets[start : start + batch_size]
        texts = [embed_text_for_chunk(c) for c in batch]
        vectors = embedder.embed_documents(texts)

        for chunk, vector in zip(batch, vectors, strict=True):
            if len(vector) != embedder.dimensions:
                msg = (
                    f"Embedding for {chunk.id} has length {len(vector)}, "
                    f"expected {embedder.dimensions}"
                )
                raise ValueError(msg)
            embeddings[chunk.id] = vector

        print(
            f"  embedded batch {batch_idx + 1}/{total_batches} "
            f"({len(batch)} chunks, {len(embeddings)} total vectors)"
        )

    return embeddings


def reconcile(
    store: ChunkStore,
    chunks: list[ChunkRecord],
) -> StorageReport:
    expected_embedded = sum(1 for c in chunks if is_embed_target(c))
    rows = store.count_rows()
    embedded = store.count_embedded()
    parents_embedded = store.count_parents_embedded()
    by_type = store.count_by_type()
    mismatches: list[str] = []

    if rows != len(chunks):
        mismatches.append(f"rows ({rows}) != total chunks ({len(chunks)})")
    if embedded != expected_embedded:
        mismatches.append(
            f"embedded ({embedded}) != expected child+table count ({expected_embedded})"
        )
    if parents_embedded != 0:
        mismatches.append(f"parent rows with embedding ({parents_embedded}) != 0")

    expected_by_type: dict[str, int] = {}
    for chunk in chunks:
        key = str(chunk.chunk_type)
        expected_by_type[key] = expected_by_type.get(key, 0) + 1
    for chunk_type, expected in sorted(expected_by_type.items()):
        actual = by_type.get(chunk_type, 0)
        if actual != expected:
            mismatches.append(f"by_type {chunk_type}: stored {actual} != expected {expected}")

    passed = not mismatches
    return StorageReport(
        total_chunks=len(chunks),
        rows=rows,
        embedded=embedded,
        expected_embedded=expected_embedded,
        parents_embedded=parents_embedded,
        by_type=by_type,
        mismatches=mismatches,
        passed=passed,
    )


def write_storage_report(report: StorageReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


def format_storage_summary(report: StorageReport) -> str:
    lines = [
        f"Storage reconciliation: {'PASSED' if report.passed else 'FAILED'}",
        f"  total_chunks={report.total_chunks} rows={report.rows}",
        f"  embedded={report.embedded} expected_embedded={report.expected_embedded}",
        f"  parents_embedded={report.parents_embedded}",
        f"  by_type={report.by_type}",
    ]
    if report.mismatches:
        lines.append("  mismatches:")
        for item in report.mismatches:
            lines.append(f"    - {item}")
    return "\n".join(lines)


def run_embed_and_store(
    tickers: list[str],
    settings: Settings | None = None,
    store: ChunkStore | None = None,
    embedder: Embedder | None = None,
) -> StorageReport:
    settings = settings or get_settings()
    store = store or get_chunk_store()
    embedder = embedder or get_embedder()

    chunks_path = settings.chunks_path
    if not chunks_path.exists():
        raise FileNotFoundError(
            f"Chunks file not found: {chunks_path}. Run scripts/ingest.py first."
        )

    all_chunks = load_chunks(chunks_path)
    chunks = filter_chunks_by_tickers(all_chunks, tickers)
    if not chunks:
        raise ValueError(f"No chunks matched tickers: {', '.join(tickers)}")

    print(f"Loading {len(chunks)} chunks for {len(tickers)} ticker(s)")
    store.init_schema()

    print(f"Embedding child + table chunks via {settings.embedder_backend} backend...")
    embeddings = embed_targets(chunks, embedder, settings)

    print("Upserting chunks (parents with NULL embedding)...")
    store.upsert_chunks(chunks, embeddings)

    report = reconcile(store, chunks)
    write_storage_report(report, settings.storage_report_path)
    summary = format_storage_summary(report)
    print(summary)
    logger.info(summary)

    if not report.passed:
        raise ReconciliationError(summary)

    return report
