"""Offline storage + embedding pipeline tests (FakeEmbedder + FakeChunkStore)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ledgerlens.config import Settings
from ledgerlens.ingestion.models import ChunkRecord, ChunkType, Provenance
from ledgerlens.interfaces.embedder import FakeEmbedder
from ledgerlens.storage.fake import FakeChunkStore
from ledgerlens.storage.pipeline import (
    embed_targets,
    embed_text_for_chunk,
    is_embed_target,
    load_chunks,
    reconcile,
    run_embed_and_store,
)
from ledgerlens.storage.postgres import PostgresChunkStore, render_schema_sql


def _make_chunk(
    chunk_id: str,
    chunk_type: ChunkType,
    *,
    parent_id: str | None = None,
    text: str = "Sample chunk text.",
    summary: str | None = None,
    is_table: bool = False,
) -> ChunkRecord:
    prov = Provenance(
        company="Fake Corp",
        ticker="FAKE",
        cik="0000000001",
        form_type="10-K",
        fiscal_period="FY2024",
        section="Item 1",
        accession_no="0000000001-24-000001",
        source_url="https://example.com/filing",
        char_start=0,
        char_end=len(text),
    )
    return ChunkRecord(
        id=chunk_id,
        chunk_type=chunk_type,
        text=text,
        parent_id=parent_id,
        is_table=is_table,
        token_count=10,
        summary=summary,
        table_data={"headers": ["A"], "rows": [["1"]]} if is_table else None,
        provenance=prov,
    )


def _fixture_chunks() -> list[ChunkRecord]:
    parent = _make_chunk("p1", ChunkType.PARENT, text="Parent section text.")
    child = _make_chunk("c1", ChunkType.CHILD, parent_id="p1", text="Child chunk text.")
    table = _make_chunk(
        "t1",
        ChunkType.TABLE,
        parent_id="p1",
        text="Col1 | Col2\n1 | 2",
        summary="Revenue table FY2024",
        is_table=True,
    )
    return [parent, child, table]


@pytest.fixture
def storage_settings(tmp_path: Path) -> Settings:
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = _fixture_chunks()
    with chunks_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.model_dump(mode="json")) + "\n")

    return Settings(
        embedder_backend="fake",
        storage_backend="fake",
        processed_dir=tmp_path,
        embed_batch_size=2,
    )


def test_embed_target_selection():
    chunks = _fixture_chunks()
    targets = [c for c in chunks if is_embed_target(c)]
    assert len(targets) == 2
    assert all(c.chunk_type in (ChunkType.CHILD, ChunkType.TABLE) for c in targets)


def test_table_embed_text_uses_linearized_body_only():
    table = _make_chunk(
        "t1",
        ChunkType.TABLE,
        text="linearized rows",
        summary="Table summary",
        is_table=True,
    )
    text = embed_text_for_chunk(table)
    assert text == "linearized rows"
    assert "Table summary" not in text


def test_embed_targets_dimension(storage_settings: Settings):
    embedder = FakeEmbedder(storage_settings)
    chunks = _fixture_chunks()
    embeddings = embed_targets(chunks, embedder, storage_settings)

    assert set(embeddings.keys()) == {"c1", "t1"}
    for vector in embeddings.values():
        assert len(vector) == storage_settings.embedder_dimensions


def test_upsert_idempotent(storage_settings: Settings):
    store = FakeChunkStore()
    embedder = FakeEmbedder(storage_settings)
    chunks = _fixture_chunks()
    embeddings = embed_targets(chunks, embedder, storage_settings)

    store.upsert_chunks(chunks, embeddings)
    first_count = store.count_rows()
    store.upsert_chunks(chunks, embeddings)
    assert store.count_rows() == first_count


def test_provenance_round_trip(storage_settings: Settings):
    store = FakeChunkStore()
    embedder = FakeEmbedder(storage_settings)
    chunks = _fixture_chunks()
    embeddings = embed_targets(chunks, embedder, storage_settings)
    store.upsert_chunks(chunks, embeddings)

    row = store.get_row("c1")
    assert row is not None
    assert row["ticker"] == "FAKE"
    assert row["section"] == "Item 1"
    assert row["accession_no"] == "0000000001-24-000001"
    assert row["char_start"] == 0


def test_reconciliation_passes_clean_fixture(storage_settings: Settings):
    store = FakeChunkStore()
    embedder = FakeEmbedder(storage_settings)
    chunks = _fixture_chunks()
    embeddings = embed_targets(chunks, embedder, storage_settings)
    store.upsert_chunks(chunks, embeddings)

    report = reconcile(store, chunks)
    assert report.passed
    assert report.rows == 3
    assert report.embedded == 2
    assert report.parents_embedded == 0


def test_reconciliation_raises_on_missing_embedding(storage_settings: Settings):
    store = FakeChunkStore()
    chunks = _fixture_chunks()
    # Upsert with only child embedded — table missing
    store.upsert_chunks(chunks, {"c1": [0.1] * storage_settings.embedder_dimensions})

    report = reconcile(store, chunks)
    assert not report.passed
    assert report.embedded == 1
    assert report.expected_embedded == 2


def test_run_embed_and_store_offline(storage_settings: Settings):
    report = run_embed_and_store(
        ["FAKE"],
        settings=storage_settings,
        store=FakeChunkStore(),
        embedder=FakeEmbedder(storage_settings),
    )
    assert report.passed
    assert storage_settings.storage_report_path.exists()


def test_load_chunks_from_jsonl(storage_settings: Settings):
    loaded = load_chunks(storage_settings.chunks_path)
    assert len(loaded) == 3


def test_render_schema_uses_config_dimensions():
    settings = Settings(embedder_dimensions=1024, hnsw_m=16, hnsw_ef_construction=64)
    sql = render_schema_sql(settings)
    assert "vector(1024)" in sql
    assert "m = 16" in sql
    assert "ef_construction = 64" in sql
    assert "to_tsvector('english', text)" in sql


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
def test_postgres_round_trip_integration():
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        embedder_backend="fake",
        storage_backend="postgres",
        embed_batch_size=2,
    )
    store = PostgresChunkStore(settings)
    embedder = FakeEmbedder(settings)
    chunks = _fixture_chunks()
    embeddings = embed_targets(chunks, embedder, settings)

    store.init_schema()
    store.upsert_chunks(chunks, embeddings)
    report = reconcile(store, chunks)
    assert report.passed

    with store._connect() as conn:  # noqa: SLF001 — integration test exercises register_vector
        with conn.cursor() as cur:
            cur.execute(
                "SELECT embedding IS NULL FROM chunks WHERE id = %s",
                ("p1",),
            )
            assert cur.fetchone()[0] is True

            cur.execute(
                "SELECT embedding, table_data IS NOT NULL FROM chunks WHERE id = %s",
                ("t1",),
            )
            table_row = cur.fetchone()
            assert table_row[1] is True  # table_data stored; contents opaque here

            cur.execute(
                "SELECT embedding FROM chunks WHERE id = %s",
                ("c1",),
            )
            child_embedding = cur.fetchone()[0]
            assert child_embedding is not None
            assert len(child_embedding) == settings.embedder_dimensions

            cur.execute(
                "SELECT vector_dims(embedding) FROM chunks WHERE id = %s",
                ("c1",),
            )
            assert cur.fetchone()[0] == settings.embedder_dimensions
