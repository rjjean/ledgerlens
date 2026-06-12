"""Structure-aware parent/child chunking with intact tables."""

from __future__ import annotations

import re
import uuid
from functools import lru_cache

import tiktoken

from ledgerlens.config import Settings
from ledgerlens.ingestion.models import ChunkRecord, ChunkType, Provenance, RawFiling, Section
from ledgerlens.ingestion.sections import prose_without_tables

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@lru_cache(maxsize=1)
def _encoding():
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_encoding().encode(text))


def locate_span(full_text: str, needle: str, hint_start: int = 0) -> tuple[int, int]:
    """Find document-level char offsets for a substring."""
    if not needle:
        return hint_start, hint_start
    pos = full_text.find(needle, max(0, hint_start))
    if pos < 0:
        pos = max(0, hint_start)
        return pos, pos + len(needle)
    return pos, pos + len(needle)


def _make_provenance(
    filing: RawFiling,
    section_item: str,
    char_start: int,
    char_end: int,
) -> Provenance:
    return Provenance(
        company=filing.company,
        ticker=filing.ticker,
        cik=filing.cik,
        form_type=filing.form_type,
        fiscal_period=filing.fiscal_period,
        section=section_item,
        accession_no=filing.accession_no,
        source_url=filing.source_url,
        char_start=char_start,
        char_end=char_end,
    )


def _chunk_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def _split_oversized_paragraph(text: str, max_tokens: int) -> list[str]:
    if count_tokens(text) <= max_tokens:
        return [text]
    sentences = _SENTENCE_SPLIT_RE.split(text)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        sentence_tokens = count_tokens(sentence)
        if sentence_tokens > max_tokens:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_tokens = 0
            words = sentence.split()
            buf: list[str] = []
            buf_tokens = 0
            for word in words:
                word_tokens = count_tokens(word + " ")
                if buf and buf_tokens + word_tokens > max_tokens:
                    chunks.append(" ".join(buf))
                    buf = [word]
                    buf_tokens = count_tokens(word)
                else:
                    buf.append(word)
                    buf_tokens += word_tokens
            if buf:
                chunks.append(" ".join(buf))
            continue

        if current and current_tokens + sentence_tokens > max_tokens:
            chunks.append(" ".join(current))
            current = [sentence]
            current_tokens = sentence_tokens
        else:
            current.append(sentence)
            current_tokens += sentence_tokens
    if current:
        chunks.append(" ".join(current))
    return chunks


def _child_chunks_from_prose(
    prose: str,
    settings: Settings,
    hint_start: int,
    full_text: str,
) -> list[tuple[str, int, int]]:
    """Split prose into child texts with document-level offsets."""
    if not prose:
        return []

    paragraphs = _split_paragraphs(prose)
    expanded: list[str] = []
    for paragraph in paragraphs:
        expanded.extend(_split_oversized_paragraph(paragraph, settings.child_max_tokens))

    children: list[tuple[str, int, int]] = []
    search_from = hint_start
    buffer: list[str] = []
    buffer_tokens = 0

    def flush_buffer() -> None:
        nonlocal search_from, buffer, buffer_tokens
        if not buffer:
            return
        child_text = "\n\n".join(buffer)
        start, end = locate_span(full_text, child_text, search_from)
        children.append((child_text, start, end))
        search_from = end
        if settings.child_overlap_tokens > 0 and buffer:
            overlap = buffer[-1]
            buffer = [overlap]
            buffer_tokens = count_tokens(overlap)
        else:
            buffer = []
            buffer_tokens = 0

    target = settings.child_target_tokens
    max_tokens = settings.child_max_tokens

    for paragraph in expanded:
        paragraph_tokens = count_tokens(paragraph)
        if buffer and buffer_tokens + paragraph_tokens > max_tokens:
            flush_buffer()
        if paragraph_tokens > max_tokens:
            flush_buffer()
            start, end = locate_span(full_text, paragraph, search_from)
            children.append((paragraph, start, end))
            search_from = end
            continue

        buffer.append(paragraph)
        buffer_tokens += paragraph_tokens
        if buffer_tokens >= target:
            flush_buffer()

    flush_buffer()
    return children


def chunk_sections(
    filing: RawFiling,
    sections: list[Section],
    settings: Settings,
) -> list[ChunkRecord]:
    records: list[ChunkRecord] = []
    prefix = f"{filing.ticker}-{filing.accession_no}"

    for section in sections:
        section_hint = section.section_char_start or 0

        for table in section.tables:
            table_id = _chunk_id(f"{prefix}-table-{table.table_id}")
            char_start = table.char_start
            char_end = table.char_end
            if char_end <= char_start:
                char_start, char_end = locate_span(
                    filing.full_text, table.linearized, section_hint
                )
            records.append(
                ChunkRecord(
                    id=table_id,
                    chunk_type=ChunkType.TABLE,
                    text=table.linearized,
                    parent_id=None,
                    is_table=True,
                    token_count=count_tokens(table.summary),
                    summary=table.summary,
                    table_data={
                        "headers": table.headers,
                        "rows": table.rows,
                        "table_id": table.table_id,
                    },
                    provenance=_make_provenance(filing, section.item, char_start, char_end),
                )
            )

        prose = prose_without_tables(section)
        if not prose:
            continue

        parent_id = _chunk_id(f"{prefix}-parent-{section.item.replace(' ', '')}")
        parent_start, parent_end = locate_span(filing.full_text, prose, section_hint)
        if section.section_char_start is not None and section.section_char_end is not None:
            parent_start = section.section_char_start
            parent_end = section.section_char_end

        records.append(
            ChunkRecord(
                id=parent_id,
                chunk_type=ChunkType.PARENT,
                text=prose,
                parent_id=None,
                is_table=False,
                token_count=count_tokens(prose),
                provenance=_make_provenance(filing, section.item, parent_start, parent_end),
            )
        )

        for child_text, char_start, char_end in _child_chunks_from_prose(
            prose, settings, parent_start, filing.full_text
        ):
            records.append(
                ChunkRecord(
                    id=_chunk_id(f"{prefix}-child-{section.item.replace(' ', '')}"),
                    chunk_type=ChunkType.CHILD,
                    text=child_text,
                    parent_id=parent_id,
                    is_table=False,
                    token_count=count_tokens(child_text),
                    provenance=_make_provenance(filing, section.item, char_start, char_end),
                )
            )

    return records
