"""Offline ingestion pipeline tests via FakeFilingSource."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ledgerlens.config import Settings
from ledgerlens.ingestion.models import ChunkType, FilingCandidate
from ledgerlens.ingestion.pipeline import process_ticker, run_ingestion, write_sample
from ledgerlens.ingestion.models import ChunkRecord, ChunkType, Provenance
from ledgerlens.ingestion.quality import (
    dedupe_candidates,
    validate_child_token_sizes,
    validate_provenance,
)
from ledgerlens.ingestion.sources import FakeFilingSource, get_filing_source


@pytest.fixture
def fake_settings(tmp_path: Path) -> Settings:
    fixture = Path("data/fixtures/fake_filing.json").resolve()
    return Settings(
        filing_source="fake",
        fixture_path=fixture,
        processed_dir=tmp_path / "processed",
        sample_path=tmp_path / "samples" / "chunks_sample.jsonl",
        child_target_tokens=100,
        child_max_tokens=150,
        child_overlap_tokens=0,
    )


def test_fake_filing_source_offline(fake_settings: Settings):
    source = FakeFilingSource(fake_settings)
    candidates = source.list_candidates("FAKE", ["10-K"])
    assert len(candidates) == 1
    filing = source.fetch_filing(candidates[0])
    assert filing.ticker == "FAKE"
    assert len(filing.sections) >= 4


def test_pipeline_produces_chunks_with_provenance(fake_settings: Settings):
    source = FakeFilingSource(fake_settings)
    chunks, result = process_ticker("FAKE", source, fake_settings)
    assert result is not None
    assert result.status == "succeeded"
    assert chunks
    assert not validate_provenance(chunks)

    types = {chunk.chunk_type for chunk in chunks}
    assert ChunkType.PARENT in types
    assert ChunkType.CHILD in types
    assert ChunkType.TABLE in types

    table_chunks = [c for c in chunks if c.chunk_type == ChunkType.TABLE]
    assert table_chunks[0].summary
    assert table_chunks[0].table_data
    assert table_chunks[0].parent_id is not None
    assert "|" in table_chunks[0].text


def test_soft_token_oversize_warns_not_quarantines(fake_settings: Settings):
    source = FakeFilingSource(fake_settings)
    _, result = process_ticker("FAKE", source, fake_settings)
    assert result is not None
    assert result.status == "succeeded"


def test_child_token_soft_max_is_warning_only(fake_settings: Settings):
    settings = fake_settings.model_copy(update={"child_max_tokens": 10, "child_hard_max_tokens": 800})
    text = "word " * 50
    chunk = ChunkRecord(
        id="child-1",
        chunk_type=ChunkType.CHILD,
        text=text,
        parent_id="parent-1",
        token_count=50,
        provenance=Provenance(
            company="C",
            ticker="T",
            cik="1",
            form_type="10-K",
            fiscal_period="2024-12-31",
            section="Item 1",
            accession_no="acc",
            source_url="https://example.com",
            char_start=0,
            char_end=len(text),
        ),
    )
    errors, warnings = validate_child_token_sizes([chunk], settings)
    assert not errors
    assert warnings


def test_child_token_hard_max_quarantines(fake_settings: Settings):
    settings = fake_settings.model_copy(update={"child_hard_max_tokens": 20})
    text = "word " * 500
    chunk = ChunkRecord(
        id="child-1",
        chunk_type=ChunkType.CHILD,
        text=text,
        parent_id="parent-1",
        token_count=500,
        provenance=Provenance(
            company="C",
            ticker="T",
            cik="1",
            form_type="10-K",
            fiscal_period="2024-12-31",
            section="Item 1",
            accession_no="acc",
            source_url="https://example.com",
            char_start=0,
            char_end=len(text),
        ),
    )
    errors, warnings = validate_child_token_sizes([chunk], settings)
    assert errors
    assert not warnings


def test_dedup_prefers_amendment_by_filing_date():
    base = dict(
        ticker="FAKE",
        company="Fake Tech Inc.",
        cik="0001234567",
        fiscal_period="2024-12-31",
        source_url="https://example.com",
    )
    original = FilingCandidate(
        **base,
        form_type="10-K",
        filing_date="2025-02-01",
        accession_no="0001234567-25-000001",
    )
    amendment = FilingCandidate(
        **base,
        form_type="10-K/A",
        filing_date="2025-03-15",
        accession_no="0001234567-25-000002",
    )
    older_period = FilingCandidate(
        ticker=base["ticker"],
        company=base["company"],
        cik=base["cik"],
        fiscal_period="2023-12-31",
        source_url=base["source_url"],
        form_type="10-K/A",
        filing_date="2025-04-01",
        accession_no="0001234567-24-000099",
    )
    selected = dedupe_candidates([original, amendment, older_period])
    assert len(selected) == 1
    assert selected[0].accession_no == amendment.accession_no
    assert selected[0].form_type == "10-K/A"


def test_run_ingestion_writes_outputs(fake_settings: Settings, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FILING_SOURCE", "fake")
    report = run_ingestion(["FAKE"], settings=fake_settings)
    assert report.succeeded == 1
    assert report.quarantined == 0
    assert fake_settings.chunks_path.exists()
    assert fake_settings.quality_report_path.exists()

    lines = fake_settings.chunks_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 5
    first = json.loads(lines[0])
    assert "chunk_type" in first
    assert "provenance" in first


def test_get_filing_source_factory(fake_settings: Settings):
    os.environ["FILING_SOURCE"] = "fake"
    source = get_filing_source(fake_settings)
    assert isinstance(source, FakeFilingSource)


def test_write_sample_committed_file(fake_settings: Settings):
    """Generate the committed sample file from the fake fixture pipeline."""
    source = FakeFilingSource(fake_settings)
    chunks, result = process_ticker("FAKE", source, fake_settings)
    assert result.status == "succeeded"
    sample_path = Path("data/samples/chunks_sample.jsonl")
    write_sample(chunks, sample_path, limit=20)
    assert sample_path.exists()
    assert len(sample_path.read_text(encoding="utf-8").strip().splitlines()) <= 20
