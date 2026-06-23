"""Neon/Postgres ChunkStore — psycopg and pgvector imported only here."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ledgerlens.config import Settings, get_settings
from ledgerlens.ingestion.models import ChunkRecord, ChunkType
from ledgerlens.storage.store import ChunkStore

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_UPSERT_SQL = """
INSERT INTO chunks (
    id, chunk_type, text, parent_id, is_table, token_count, summary, table_data,
    company, ticker, cik, form_type, fiscal_period, section,
    accession_no, source_url, char_start, char_end, embedding
) VALUES (
    %(id)s, %(chunk_type)s, %(text)s, %(parent_id)s, %(is_table)s, %(token_count)s,
    %(summary)s, %(table_data)s::jsonb, %(company)s, %(ticker)s, %(cik)s,
    %(form_type)s, %(fiscal_period)s, %(section)s, %(accession_no)s,
    %(source_url)s, %(char_start)s, %(char_end)s, %(embedding)s
)
ON CONFLICT (id) DO UPDATE SET
    chunk_type = EXCLUDED.chunk_type,
    text = EXCLUDED.text,
    parent_id = EXCLUDED.parent_id,
    is_table = EXCLUDED.is_table,
    token_count = EXCLUDED.token_count,
    summary = EXCLUDED.summary,
    table_data = EXCLUDED.table_data,
    company = EXCLUDED.company,
    ticker = EXCLUDED.ticker,
    cik = EXCLUDED.cik,
    form_type = EXCLUDED.form_type,
    fiscal_period = EXCLUDED.fiscal_period,
    section = EXCLUDED.section,
    accession_no = EXCLUDED.accession_no,
    source_url = EXCLUDED.source_url,
    char_start = EXCLUDED.char_start,
    char_end = EXCLUDED.char_end,
    embedding = EXCLUDED.embedding
"""


def render_schema_sql(settings: Settings) -> str:
    template = _SCHEMA_PATH.read_text(encoding="utf-8")
    return template.format(
        embedder_dimensions=settings.embedder_dimensions,
        hnsw_m=settings.hnsw_m,
        hnsw_ef_construction=settings.hnsw_ef_construction,
        fts_language=settings.fts_language,
    )


def _params_from_record(
    record: ChunkRecord,
    embedding: list[float] | None,
) -> dict[str, Any]:
    prov = record.provenance
    table_data = json.dumps(record.table_data) if record.table_data is not None else None
    return {
        "id": record.id,
        "chunk_type": str(record.chunk_type),
        "text": record.text,
        "parent_id": record.parent_id,
        "is_table": record.is_table,
        "token_count": record.token_count,
        "summary": record.summary,
        "table_data": table_data,
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


class PostgresChunkStore(ChunkStore):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.database_url:
            raise ValueError(
                "DATABASE_URL is required when storage_backend=postgres. "
                "Copy .env.example to .env and add your Neon connection string."
            )

    def _connect(self):
        import psycopg  # noqa: PLC0415
        from pgvector.psycopg import register_vector  # noqa: PLC0415

        conn = psycopg.connect(self._settings.database_url)
        register_vector(conn)
        return conn

    def init_schema(self) -> None:
        ddl = render_schema_sql(self._settings)
        with self._connect() as conn:
            with conn.cursor() as cur:
                for statement in _split_sql(ddl):
                    cur.execute(statement)
            conn.commit()
        logger.info("Schema initialized (chunks table + indexes)")

    def upsert_chunks(
        self,
        records: list[ChunkRecord],
        embeddings: dict[str, list[float]],
    ) -> None:
        parents = [r for r in records if r.chunk_type == ChunkType.PARENT]
        others = [r for r in records if r.chunk_type != ChunkType.PARENT]
        ordered = parents + others
        batch_size = self._settings.embed_batch_size

        with self._connect() as conn:
            with conn.cursor() as cur:
                for start in range(0, len(ordered), batch_size):
                    batch = ordered[start : start + batch_size]
                    params_list = [
                        _params_from_record(
                            record,
                            None if record.chunk_type == ChunkType.PARENT
                            else embeddings.get(record.id),
                        )
                        for record in batch
                    ]
                    cur.executemany(_UPSERT_SQL, params_list)
            conn.commit()

    def count_rows(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM chunks")
                return int(cur.fetchone()[0])

    def count_embedded(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL")
                return int(cur.fetchone()[0])

    def count_by_type(self) -> dict[str, int]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT chunk_type, COUNT(*) FROM chunks GROUP BY chunk_type ORDER BY chunk_type"
                )
                return {row[0]: int(row[1]) for row in cur.fetchall()}

    def count_parents_embedded(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM chunks "
                    "WHERE chunk_type = %s AND embedding IS NOT NULL",
                    (ChunkType.PARENT,),
                )
                return int(cur.fetchone()[0])


def _split_sql(ddl: str) -> list[str]:
    statements: list[str] = []
    for part in ddl.split(";"):
        stripped = part.strip()
        if stripped:
            statements.append(stripped)
    return statements
