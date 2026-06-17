"""Pure section conversion and normalization — no edgartools imports."""

from __future__ import annotations

import logging
import re

from ledgerlens.ingestion.models import RawSectionPayload, Section, TableBlock

logger = logging.getLogger(__name__)

EXPECTED_10K_ITEMS: list[str] = ["Item 1", "Item 1A", "Item 7", "Item 8"]

_WHITESPACE_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Normalize whitespace while preserving paragraph breaks."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def parse_linearized_table(linearized: str) -> tuple[list[str], list[list[str]]]:
    """Parse a pipe- or tab-delimited table into headers and rows."""
    lines = [line.strip() for line in linearized.splitlines() if line.strip()]
    if not lines:
        return [], []

    rows: list[list[str]] = []
    for line in lines:
        if "|" in line:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
        else:
            cells = [cell.strip() for cell in re.split(r"\t+", line) if cell.strip()]
        if cells:
            rows.append(cells)

    if not rows:
        return [], []

    headers = rows[0]
    data_rows = rows[1:]
    if data_rows and all(not cell for cell in data_rows[0]):
        data_rows = data_rows[1:]
    return headers, data_rows


def build_table_summary(item: str, headers: list[str], rows: list[list[str]]) -> str:
    cols = len(headers) if headers else (len(rows[0]) if rows else 0)
    row_count = len(rows)
    header_hint = headers[0] if headers else "data"
    return f"Table in {item}: {header_hint} ({row_count} rows x {cols} columns)"


def payloads_to_sections(payloads: list[RawSectionPayload]) -> list[Section]:
    """Convert raw section payloads into typed Section objects."""
    sections: list[Section] = []
    for payload in payloads:
        text = clean_text(payload.text)
        if not text and not payload.tables:
            logger.warning("Skipping empty section %s", payload.item)
            continue

        tables: list[TableBlock] = []
        for raw_table in payload.tables:
            headers = raw_table.headers
            rows = raw_table.rows
            if not headers and not rows:
                headers, rows = parse_linearized_table(raw_table.linearized)
            summary = raw_table.summary or build_table_summary(payload.item, headers, rows)
            tables.append(
                TableBlock(
                    table_id=raw_table.table_id,
                    headers=headers,
                    rows=rows,
                    linearized=clean_text(raw_table.linearized),
                    summary=summary,
                    char_start=raw_table.char_start,
                    char_end=raw_table.char_end,
                )
            )

        sections.append(
            Section(
                item=payload.item,
                title=payload.title,
                text=text,
                tables=tables,
                section_char_start=payload.section_char_start,
                section_char_end=payload.section_char_end,
            )
        )
    return sections


def prose_without_tables(section: Section) -> str:
    """Return section prose with table bodies removed (tables become separate chunks)."""
    prose = section.text
    for table in section.tables:
        if table.linearized and table.linearized in prose:
            prose = prose.replace(table.linearized, "", 1)
        else:
            prose = prose.replace(table.linearized.strip(), "", 1)
    return clean_text(prose)


def missing_expected_items(found_items: list[str]) -> list[str]:
    found = {item.strip() for item in found_items}
    return [item for item in EXPECTED_10K_ITEMS if item not in found]
