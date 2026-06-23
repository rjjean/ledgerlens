"""Offline ingestion pipeline tests via FakeFilingSource."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ledgerlens.config import Settings
from ledgerlens.ingestion.models import ChunkRecord, ChunkType, FilingCandidate, Provenance
from ledgerlens.ingestion.pipeline import process_ticker, run_ingestion, write_sample
from ledgerlens.ingestion.quality import (
    dedupe_candidates,
    validate_child_token_sizes,
    validate_provenance,
)
from ledgerlens.ingestion.sources import FakeFilingSource, get_filing_source, select_filing_candidate


def _write_fixture(tmp_path: Path, sections: list[dict]) -> Path:
    base = json.loads(Path("data/fixtures/fake_filing.json").resolve().read_text(encoding="utf-8"))
    base["sections"] = sections
    path = tmp_path / "filing.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


def _base_sections() -> list[dict]:
    data = json.loads(Path("data/fixtures/fake_filing.json").resolve().read_text(encoding="utf-8"))
    return list(data["sections"])


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


def test_select_filing_excludes_amendment_for_mvp():
    base = dict(
        ticker="AMD",
        company="Advanced Micro Devices Inc.",
        cik="0000002488",
        fiscal_period="2024-12-28",
        source_url="https://example.com",
    )
    original = FilingCandidate(
        **base,
        form_type="10-K",
        filing_date="2025-02-01",
        accession_no="0000002488-25-000010",
    )
    partial_amendment = FilingCandidate(
        **base,
        form_type="10-K/A",
        filing_date="2026-02-15",
        accession_no="0000002488-26-000021",
    )
    chosen = select_filing_candidate([partial_amendment, original])
    assert chosen is not None
    assert chosen.form_type == "10-K"
    assert chosen.accession_no == original.accession_no


def test_dedup_keeps_latest_original_per_period():
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
    older_period = FilingCandidate(
        ticker=base["ticker"],
        company=base["company"],
        cik=base["cik"],
        fiscal_period="2023-12-31",
        source_url=base["source_url"],
        form_type="10-K",
        filing_date="2025-04-01",
        accession_no="0001234567-24-000099",
    )
    selected = dedupe_candidates([original, older_period])
    assert len(selected) == 1
    assert selected[0].accession_no == original.accession_no
    assert selected[0].form_type == "10-K"


def test_ingestion_selects_complete_10k_over_partial_amendment(fake_settings: Settings):
    fixture = Path("data/fixtures/fake_amd_10k_vs_amendment.json").resolve()
    settings = fake_settings.model_copy(update={"fixture_path": fixture})
    source = FakeFilingSource(settings)

    candidates = source.list_candidates("AMD", ["10-K"])
    chosen = select_filing_candidate(candidates)
    assert chosen is not None
    assert chosen.form_type == "10-K"
    assert chosen.accession_no == "0000002488-25-000010"

    chunks, result = process_ticker("AMD", source, settings)
    assert result.status == "succeeded"
    assert chunks
    sections = {chunk.provenance.section for chunk in chunks}
    assert "Item 1" in sections
    assert "Item 1A" in sections
    assert "Item 7A" in sections


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


def test_non_critical_placeholder_section_keeps_filing(tmp_path: Path, fake_settings: Settings):
    sections = _base_sections() + [
        {
            "item": "Item 6",
            "title": "Selected Financial Data",
            "text": "[Reserved]",
            "tables": [],
            "section_char_start": 0,
            "section_char_end": 10,
        }
    ]
    settings = fake_settings.model_copy(
        update={"fixture_path": _write_fixture(tmp_path, sections)}
    )
    source = FakeFilingSource(settings)
    chunks, result = process_ticker("FAKE", source, settings)

    assert result.status == "succeeded"
    assert chunks
    assert not any(w for w in result.warnings if "Item 6" in w)
    assert "Item 6" not in {chunk.provenance.section for chunk in chunks}


def test_non_critical_empty_section_warns_not_quarantines(tmp_path: Path, fake_settings: Settings):
    sections = _base_sections() + [
        {
            "item": "Item 5",
            "title": "Market for Registrant's Common Equity",
            "text": "",
            "tables": [],
            "section_char_start": 0,
            "section_char_end": 0,
        }
    ]
    settings = fake_settings.model_copy(
        update={"fixture_path": _write_fixture(tmp_path, sections)}
    )
    source = FakeFilingSource(settings)
    chunks, result = process_ticker("FAKE", source, settings)

    assert result.status == "succeeded"
    assert chunks
    assert any("Item 5" in warning for warning in result.warnings)
    assert "Item 5" not in {chunk.provenance.section for chunk in chunks}


def test_critical_garbled_section_quarantines_filing(tmp_path: Path, fake_settings: Settings):
    sections = _base_sections()
    for section in sections:
        if section["item"] == "Item 1":
            section["text"] = ""
    settings = fake_settings.model_copy(
        update={"fixture_path": _write_fixture(tmp_path, sections)}
    )
    source = FakeFilingSource(settings)
    chunks, result = process_ticker("FAKE", source, settings)

    assert result.status == "quarantined"
    assert not chunks
    assert result.reason is not None
    assert "Item 1" in result.reason
