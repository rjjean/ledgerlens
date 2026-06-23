"""Orchestrate ingestion: fetch → extract → chunk → quality-check → write."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ledgerlens.config import Settings, get_settings
from ledgerlens.ingestion.chunking import chunk_sections
from ledgerlens.ingestion.models import ChunkRecord, FilingQualityResult, QualityReport
from ledgerlens.ingestion.quality import (
    assess_filing,
    build_quality_report,
    filter_filing_sections,
    format_quality_summary,
    write_quality_report,
)
from ledgerlens.ingestion.sections import payloads_to_sections
from ledgerlens.ingestion.sources import FilingSource, get_filing_source, select_filing_candidate

logger = logging.getLogger(__name__)


def process_ticker(
    ticker: str,
    source: FilingSource,
    settings: Settings,
) -> tuple[list[ChunkRecord], FilingQualityResult | None]:
    """Fetch, chunk, and quality-check one ticker."""
    candidates = source.list_candidates(ticker, settings.form_types)
    if not candidates:
        logger.warning("No candidates for %s", ticker)
        return [], FilingQualityResult(
            ticker=ticker,
            accession_no="",
            status="quarantined",
            reason="no filings found",
        )

    candidate = select_filing_candidate(candidates)
    if candidate is None:
        return [], FilingQualityResult(
            ticker=ticker,
            accession_no="",
            status="quarantined",
            reason="no original 10-K found (amendments excluded for MVP)",
        )

    logger.info(
        "Processing %s: %s %s (period=%s, filed=%s)",
        ticker,
        candidate.form_type,
        candidate.accession_no,
        candidate.fiscal_period,
        candidate.filing_date,
    )

    try:
        raw_filing = source.fetch_filing(candidate)
    except Exception as exc:
        logger.exception("Failed to fetch %s", ticker)
        return [], FilingQualityResult(
            ticker=ticker,
            accession_no=candidate.accession_no,
            status="quarantined",
            reason=f"fetch failed: {exc}",
        )

    raw_filing, section_warnings, section_errors = filter_filing_sections(raw_filing, settings)
    if section_errors:
        for reason in section_errors:
            logger.warning("[%s] %s", ticker, reason)
        return [], FilingQualityResult(
            ticker=ticker,
            accession_no=raw_filing.accession_no,
            status="quarantined",
            reason="; ".join(section_errors),
            warnings=section_warnings,
            sections_found=[section.item for section in raw_filing.sections],
        )

    sections = payloads_to_sections(raw_filing.sections)
    chunks = chunk_sections(raw_filing, sections, settings)
    result = assess_filing(raw_filing, chunks, settings, section_warnings=section_warnings)

    if result.status == "quarantined":
        return [], result
    return chunks, result


def run_ingestion(
    tickers: list[str],
    settings: Settings | None = None,
    source: FilingSource | None = None,
) -> QualityReport:
    settings = settings or get_settings()
    source = source or get_filing_source(settings)

    all_chunks: list[ChunkRecord] = []
    results: list[FilingQualityResult] = []

    for ticker in tickers:
        chunks, result = process_ticker(ticker, source, settings)
        if result is not None:
            results.append(result)
        if chunks:
            all_chunks.extend(chunks)

    report = build_quality_report(
        filings_attempted=len(tickers),
        results=results,
        total_chunks=len(all_chunks),
    )

    if all_chunks:
        write_chunks(all_chunks, settings.chunks_path)
        write_sample(all_chunks, settings.sample_path, limit=20)

    write_quality_report(report, settings.quality_report_path)
    summary = format_quality_summary(report)
    print(summary)
    logger.info(summary)
    return report


def write_chunks(chunks: list[ChunkRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.model_dump(mode="json")) + "\n")


def write_sample(chunks: list[ChunkRecord], path: Path, limit: int = 20) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample = chunks[:limit]
    with path.open("w", encoding="utf-8") as handle:
        for chunk in sample:
            handle.write(json.dumps(chunk.model_dump(mode="json")) + "\n")
