"""Text preparation for retrieval-side consumers (rerank, future synthesis)."""

from __future__ import annotations

from typing import Any

from ledgerlens.ingestion.models import ChunkRecord, ChunkType


def linearize_table_data(table_data: dict[str, Any] | None) -> str:
    """Rebuild a linearized table body from structured ``table_data``."""
    if not table_data:
        return ""
    headers = table_data.get("headers") or []
    rows = table_data.get("rows") or []
    lines: list[str] = []
    if headers:
        lines.append(" | ".join(str(h) for h in headers))
    for row in rows:
        lines.append(" | ".join(str(cell) for cell in row))
    return "\n".join(lines).strip()


def rerank_text_for_chunk(chunk: ChunkRecord) -> str:
    """Text fed to the cross-encoder for one candidate.

    Tables: prefer the full linearized body. Stored ``chunk.text`` is the
    ingest-time linearization; when ``table_data`` rebuilds a longer body, use
    that so empty/truncated stubs don't starve the reranker of structure.
    """
    body = (chunk.text or "").strip()
    if chunk.chunk_type == ChunkType.TABLE or chunk.is_table:
        rebuilt = linearize_table_data(chunk.table_data)
        if len(rebuilt) > len(body):
            return rebuilt
        return body
    return body
