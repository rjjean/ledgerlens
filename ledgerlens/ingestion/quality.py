"""Data-quality checks for the ingestion pipeline."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ledgerlens.config import Settings
from ledgerlens.ingestion.chunking import count_tokens
from ledgerlens.ingestion.models import (
    ChunkRecord,
    ChunkType,
    FilingCandidate,
    FilingQualityResult,
    Provenance,
    QualityReport,
    RawFiling,
)
from ledgerlens.ingestion.sections import missing_expected_items

logger = logging.getLogger(__name__)

_GARBLED_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_PROVENANCE_FIELDS = tuple(Provenance.model_fields.keys())


def is_garbled(text: str) -> bool:
    if not text or not text.strip():
        return True
    if _GARBLED_RE.search(text):
        return True
    printable_ratio = sum(ch.isprintable() or ch in "\n\t" for ch in text) / len(text)
    return printable_ratio < 0.85


def dedupe_candidates(candidates: list[FilingCandidate]) -> list[FilingCandidate]:
    """Keep the latest filing_date per (CIK, fiscal_period), then latest period per CIK."""
    by_period: dict[tuple[str, str], FilingCandidate] = {}
    for candidate in candidates:
        key = (candidate.cik, candidate.fiscal_period)
        existing = by_period.get(key)
        if existing is None or candidate.filing_date > existing.filing_date:
            by_period[key] = candidate

    by_cik: dict[str, FilingCandidate] = {}
    for candidate in by_period.values():
        existing = by_cik.get(candidate.cik)
        if existing is None or candidate.fiscal_period > existing.fiscal_period:
            by_cik[candidate.cik] = candidate
    return list(by_cik.values())


def validate_provenance(chunks: list[ChunkRecord]) -> list[str]:
    errors: list[str] = []
    for chunk in chunks:
        data = chunk.provenance.model_dump()
        for field in _PROVENANCE_FIELDS:
            value = data.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(f"{chunk.id}: missing provenance field {field}")
        if chunk.provenance.char_end < chunk.provenance.char_start:
            errors.append(f"{chunk.id}: invalid char offsets")
    return errors


def validate_child_token_sizes(
    chunks: list[ChunkRecord],
    settings: Settings,
) -> tuple[list[str], list[str]]:
    """Return (quarantine_errors, warnings).

    Exceeding child_max_tokens is a soft warning — a single long paragraph can
    legitimately exceed the target. Only empty children or tokens above
    child_hard_max_tokens trigger quarantine.
    """
    errors: list[str] = []
    warnings: list[str] = []
    for chunk in chunks:
        if chunk.chunk_type != ChunkType.CHILD:
            continue
        tokens = count_tokens(chunk.text)
        if tokens == 0:
            errors.append(f"{chunk.id}: empty child chunk")
        elif tokens > settings.child_hard_max_tokens:
            errors.append(
                f"{chunk.id}: child has {tokens} tokens "
                f"(hard max {settings.child_hard_max_tokens})"
            )
        elif tokens > settings.child_max_tokens:
            warnings.append(
                f"{chunk.id}: child has {tokens} tokens "
                f"(soft max {settings.child_max_tokens})"
            )
    return errors, warnings


def validate_parent_child_links(chunks: list[ChunkRecord]) -> list[str]:
    errors: list[str] = []
    by_id = {chunk.id: chunk for chunk in chunks}
    for chunk in chunks:
        if chunk.chunk_type in (ChunkType.CHILD, ChunkType.TABLE):
            if not chunk.parent_id:
                errors.append(f"{chunk.id}: {chunk.chunk_type} missing parent_id")
            elif chunk.parent_id not in by_id:
                errors.append(f"{chunk.id}: parent_id {chunk.parent_id} not found")
            elif by_id[chunk.parent_id].chunk_type != ChunkType.PARENT:
                errors.append(f"{chunk.id}: parent_id points to non-parent chunk")
    return errors


def assess_filing(
    filing: RawFiling,
    chunks: list[ChunkRecord],
    settings: Settings,
) -> FilingQualityResult:
    found_items = [section.item for section in filing.sections]
    missing = missing_expected_items(found_items)
    reasons: list[str] = []

    for section in filing.sections:
        if is_garbled(section.text):
            reasons.append(f"garbled section {section.item}")

    provenance_errors = validate_provenance(chunks)
    token_errors, token_warnings = validate_child_token_sizes(chunks, settings)
    link_errors = validate_parent_child_links(chunks)
    reasons.extend(provenance_errors)
    reasons.extend(token_errors)
    reasons.extend(link_errors)

    for warning in token_warnings:
        logger.warning("[%s] %s", filing.ticker, warning)

    status = "quarantined" if reasons else "succeeded"
    parent_count = sum(1 for c in chunks if c.chunk_type == ChunkType.PARENT)
    child_count = sum(1 for c in chunks if c.chunk_type == ChunkType.CHILD)
    table_count = sum(1 for c in chunks if c.chunk_type == ChunkType.TABLE)

    if status == "quarantined":
        for reason in reasons:
            logger.warning("[%s] %s", filing.ticker, reason)

    return FilingQualityResult(
        ticker=filing.ticker,
        accession_no=filing.accession_no,
        status=status,
        reason="; ".join(reasons) if reasons else None,
        warnings=token_warnings,
        sections_found=found_items,
        sections_missing=missing,
        chunk_count=len(chunks),
        parent_count=parent_count,
        child_count=child_count,
        table_count=table_count,
    )


def build_quality_report(
    filings_attempted: int,
    results: list[FilingQualityResult],
    total_chunks: int,
) -> QualityReport:
    succeeded = sum(1 for result in results if result.status == "succeeded")
    quarantined = sum(1 for result in results if result.status == "quarantined")
    return QualityReport(
        tickers_requested=filings_attempted,
        filings_attempted=filings_attempted,
        succeeded=succeeded,
        quarantined=quarantined,
        total_chunks=total_chunks,
        filings=results,
    )


def write_quality_report(report: QualityReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(), indent=2) + "\n",
        encoding="utf-8",
    )


def format_quality_summary(report: QualityReport) -> str:
    rate = report.success_rate * 100
    lines = [
        "=== Quality summary ===",
        f"Filings attempted: {report.filings_attempted}",
        f"Succeeded: {report.succeeded}",
        f"Quarantined: {report.quarantined}",
        f"Success rate: {rate:.1f}%",
        f"Total chunks: {report.total_chunks}",
    ]
    for filing in report.filings:
        if filing.status == "quarantined":
            lines.append(f"  QUARANTINED {filing.ticker} ({filing.accession_no}): {filing.reason}")
        else:
            missing = filing.sections_missing
            missing_note = f" missing={missing}" if missing else ""
            warn_note = f" warnings={len(filing.warnings)}" if filing.warnings else ""
            lines.append(
                f"  OK {filing.ticker}: chunks={filing.chunk_count} "
                f"(parents={filing.parent_count}, children={filing.child_count}, "
                f"tables={filing.table_count}){missing_note}{warn_note}"
            )
    if missing_expected := [
        item for result in report.filings for item in result.sections_missing
    ]:
        lines.append(f"Expected items not found in some filings: {sorted(set(missing_expected))}")
    return "\n".join(lines)
