"""Offline chunking tests — no network, no edgartools."""

from __future__ import annotations

from ledgerlens.config import Settings
from ledgerlens.ingestion.chunking import chunk_sections, count_tokens
from ledgerlens.ingestion.models import ChunkType, RawFiling, Section, TableBlock
from ledgerlens.ingestion.sections import prose_without_tables


def _settings(**overrides) -> Settings:
    base = {
        "child_target_tokens": 80,
        "child_max_tokens": 120,
        "child_overlap_tokens": 0,
    }
    base.update(overrides)
    return Settings(**base)


def _filing(full_text: str, sections: list[Section]) -> RawFiling:
    return RawFiling(
        ticker="FAKE",
        company="Fake Tech Inc.",
        cik="0001234567",
        form_type="10-K",
        fiscal_period="2024-12-31",
        filing_date="2025-02-15",
        accession_no="0001234567-25-000001",
        source_url="https://example.com/filing",
        full_text=full_text,
        sections=[],
    )


def test_tables_are_never_sliced():
    table_text = "| A | B |\n| 1 | 2 |\n| 3 | 4 |"
    full_text = f"Intro paragraph.\n\n{table_text}\n\nClosing paragraph."
    table = TableBlock(
        table_id="t0",
        headers=["A", "B"],
        rows=[["1", "2"], ["3", "4"]],
        linearized=table_text,
        summary="Table in Item 8: A (2 rows x 2 columns)",
        char_start=full_text.find(table_text),
        char_end=full_text.find(table_text) + len(table_text),
    )
    section = Section(item="Item 8", text=full_text, tables=[table])
    filing = _filing(full_text, [section])
    chunks = chunk_sections(filing, [section], _settings())

    table_chunks = [c for c in chunks if c.chunk_type == ChunkType.TABLE]
    parents = [c for c in chunks if c.chunk_type == ChunkType.PARENT]
    assert len(table_chunks) == 1
    assert len(parents) == 1
    assert table_chunks[0].parent_id == parents[0].id
    assert table_chunks[0].table_data is not None
    assert len(table_chunks[0].table_data["rows"]) == 2
    assert table_text in table_chunks[0].text
    assert table_chunks[0].summary is not None
    assert table_chunks[0].text not in table_chunks[0].summary


def test_children_within_token_range():
    paragraph = "Revenue increased due to strong demand. " * 40
    full_text = f"ITEM 1A.\n\n{paragraph}"
    section = Section(
        item="Item 1A",
        text=paragraph,
        section_char_start=0,
        section_char_end=len(full_text),
    )
    filing = _filing(full_text, [section])
    settings = _settings(child_target_tokens=80, child_max_tokens=120)
    chunks = chunk_sections(filing, [section], settings)

    children = [c for c in chunks if c.chunk_type == ChunkType.CHILD]
    assert len(children) >= 2
    for child in children:
        assert count_tokens(child.text) <= settings.child_max_tokens
        assert child.parent_id is not None


def test_provenance_complete_and_document_offsets():
    prose = "Cloud revenue grew eighteen percent year over year."
    full_text = f"ITEM 1. BUSINESS\n\n{prose}"
    section = Section(
        item="Item 1",
        text=prose,
        section_char_start=0,
        section_char_end=len(full_text),
    )
    filing = _filing(full_text, [section])
    chunks = chunk_sections(filing, [section], _settings(child_target_tokens=200))

    for chunk in chunks:
        prov = chunk.provenance
        assert prov.company
        assert prov.ticker == "FAKE"
        assert prov.cik
        assert prov.form_type == "10-K"
        assert prov.fiscal_period
        assert prov.section == "Item 1"
        assert prov.accession_no
        assert prov.source_url
        assert prov.char_end >= prov.char_start
        assert full_text[prov.char_start : prov.char_end]


def test_parent_child_links_resolve():
    prose = ("Risk factor paragraph one. " * 15) + "\n\n" + ("Risk factor paragraph two. " * 15)
    full_text = prose
    section = Section(item="Item 1A", text=prose)
    filing = _filing(full_text, [section])
    chunks = chunk_sections(filing, [section], _settings(child_target_tokens=60, child_max_tokens=100))

    by_id = {chunk.id: chunk for chunk in chunks}
    parents = [c for c in chunks if c.chunk_type == ChunkType.PARENT]
    children = [c for c in chunks if c.chunk_type == ChunkType.CHILD]
    assert len(parents) == 1
    assert children
    for child in children:
        assert child.parent_id == parents[0].id
        assert by_id[child.parent_id].chunk_type == ChunkType.PARENT


def test_prose_without_tables_removes_table_body():
    table_text = "| H1 | H2 |\n| v1 | v2 |"
    section_text = f"Before table.\n\n{table_text}\n\nAfter table."
    table = TableBlock(
        table_id="t0",
        headers=["H1", "H2"],
        rows=[["v1", "v2"]],
        linearized=table_text,
        summary="summary",
        char_start=0,
        char_end=len(table_text),
    )
    section = Section(item="Item 8", text=section_text, tables=[table])
    prose = prose_without_tables(section)
    assert table_text not in prose
    assert "Before table." in prose
    assert "After table." in prose
