"""Shared row → ChunkRecord mapping for ChunkStore backends."""

from __future__ import annotations

from typing import Any

from ledgerlens.ingestion.models import ChunkRecord, ChunkType, Provenance


def chunk_record_from_row(row: dict[str, Any]) -> ChunkRecord:
    chunk_type = row["chunk_type"]
    if not isinstance(chunk_type, ChunkType):
        chunk_type = ChunkType(chunk_type)

    return ChunkRecord(
        id=row["id"],
        chunk_type=chunk_type,
        text=row["text"],
        parent_id=row.get("parent_id"),
        is_table=bool(row.get("is_table", False)),
        token_count=int(row["token_count"]),
        summary=row.get("summary"),
        table_data=row.get("table_data"),
        provenance=Provenance(
            company=row["company"],
            ticker=row["ticker"],
            cik=row["cik"],
            form_type=row["form_type"],
            fiscal_period=row["fiscal_period"],
            section=row["section"],
            accession_no=row["accession_no"],
            source_url=row["source_url"],
            char_start=int(row["char_start"]),
            char_end=int(row["char_end"]),
        ),
    )
