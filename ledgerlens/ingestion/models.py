"""Pydantic models for ingestion — provenance is the citation system."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ChunkType(StrEnum):
    PARENT = "parent"
    CHILD = "child"
    TABLE = "table"


class Provenance(BaseModel):
    company: str
    ticker: str
    cik: str
    form_type: str
    fiscal_period: str
    section: str
    accession_no: str
    source_url: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)

    @model_validator(mode="after")
    def _offsets_ordered(self) -> Provenance:
        if self.char_end < self.char_start:
            msg = f"char_end ({self.char_end}) must be >= char_start ({self.char_start})"
            raise ValueError(msg)
        return self


class TableBlock(BaseModel):
    """Structured table extracted intact from a section."""

    table_id: str
    headers: list[str]
    rows: list[list[str]]
    linearized: str
    summary: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)


class Section(BaseModel):
    item: str
    title: str | None = None
    text: str
    tables: list[TableBlock] = Field(default_factory=list)
    section_char_start: int | None = None
    section_char_end: int | None = None


class RawTablePayload(BaseModel):
    table_id: str
    headers: list[str]
    rows: list[list[str]]
    linearized: str
    summary: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)


class RawSectionPayload(BaseModel):
    """Already-fetched section data — no edgartools dependency."""

    item: str
    title: str | None = None
    text: str
    tables: list[RawTablePayload] = Field(default_factory=list)
    section_char_start: int | None = None
    section_char_end: int | None = None


class FilingCandidate(BaseModel):
    """Lightweight filing metadata for dedup before full download."""

    ticker: str
    company: str
    cik: str
    form_type: str
    fiscal_period: str
    filing_date: str
    accession_no: str
    source_url: str


class RawFiling(BaseModel):
    ticker: str
    company: str
    cik: str
    form_type: str
    fiscal_period: str
    filing_date: str
    accession_no: str
    source_url: str
    full_text: str
    sections: list[RawSectionPayload] = Field(default_factory=list)


class ChunkRecord(BaseModel):
    id: str
    chunk_type: ChunkType
    text: str
    parent_id: str | None = None
    is_table: bool = False
    token_count: int = Field(ge=0)
    summary: str | None = None
    table_data: dict[str, Any] | None = None
    provenance: Provenance


class FilingQualityResult(BaseModel):
    ticker: str
    accession_no: str
    status: str  # succeeded | quarantined
    reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    sections_found: list[str] = Field(default_factory=list)
    sections_missing: list[str] = Field(default_factory=list)
    chunk_count: int = 0
    parent_count: int = 0
    child_count: int = 0
    table_count: int = 0


class QualityReport(BaseModel):
    tickers_requested: int
    filings_attempted: int
    succeeded: int
    quarantined: int
    total_chunks: int
    filings: list[FilingQualityResult] = Field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.filings_attempted == 0:
            return 0.0
        return self.succeeded / self.filings_attempted
