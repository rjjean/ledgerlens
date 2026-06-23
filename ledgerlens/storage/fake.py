"""In-memory ChunkStore for offline tests and fake-backend runs."""

from __future__ import annotations

import json
from typing import Any

from ledgerlens.config import Settings
from ledgerlens.ingestion.models import ChunkRecord, ChunkType
from ledgerlens.storage.store import ChunkStore


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

    def get_row(self, chunk_id: str) -> dict[str, Any] | None:
        row = self._rows.get(chunk_id)
        if row is None:
            return None
        return json.loads(json.dumps(row))
