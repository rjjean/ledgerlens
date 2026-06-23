"""FilingSource seam — edgartools is confined to EdgarFilingSource."""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod

from ledgerlens.config import Settings, get_settings
from ledgerlens.ingestion.models import FilingCandidate, RawFiling, RawSectionPayload, RawTablePayload
from ledgerlens.ingestion.sections import (
    build_table_summary,
    clean_text,
    parse_linearized_table,
)
from ledgerlens.ingestion.quality import dedupe_candidates

logger = logging.getLogger(__name__)

# SEC fair-access: stay well under 10 req/s (~6–7 req/s).
EDGAR_REQUEST_INTERVAL_SEC: float = 0.15

# TODO(v1): detect partial vs full 10-K/A and merge amended sections into the corpus.


class FilingSource(ABC):
    @abstractmethod
    def list_candidates(self, ticker: str, form_types: list[str]) -> list[FilingCandidate]:
        """Return filing metadata for dedup before full download."""

    @abstractmethod
    def fetch_filing(self, candidate: FilingCandidate) -> RawFiling:
        """Download and section-extract a single filing."""


class EdgarFilingSource(FilingSource):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._last_request_at: float | None = None
        self._configure_identity()

    def _configure_identity(self) -> None:
        identity = self._settings.edgar_identity
        if not identity or not identity.strip():
            raise ValueError(
                "EDGAR_IDENTITY is required before any EDGAR call. "
                "Set a real name and email in .env, e.g. "
                "EDGAR_IDENTITY='Your Name your.email@example.com'"
            )
        from edgar import set_identity

        set_identity(identity.strip())
        logger.info("EDGAR identity configured for User-Agent declaration")

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < EDGAR_REQUEST_INTERVAL_SEC:
                time.sleep(EDGAR_REQUEST_INTERVAL_SEC - elapsed)
        self._last_request_at = time.monotonic()

    def list_candidates(self, ticker: str, form_types: list[str]) -> list[FilingCandidate]:
        from edgar import Company

        self._throttle()
        company = Company(ticker)
        filings = company.get_filings(form=list(form_types))
        candidates: list[FilingCandidate] = []
        for filing in filings:
            fiscal_period = _fiscal_period_from_filing(filing)
            candidates.append(
                FilingCandidate(
                    ticker=ticker.upper(),
                    company=str(filing.company),
                    cik=str(filing.cik),
                    form_type=str(filing.form),
                    fiscal_period=fiscal_period,
                    filing_date=str(filing.filing_date),
                    accession_no=str(filing.accession_no),
                    source_url=str(filing.homepage_url),
                )
            )
        return candidates

    def fetch_filing(self, candidate: FilingCandidate) -> RawFiling:
        from edgar import Company

        self._throttle()
        company = Company(candidate.ticker)
        filings = company.get_filings(
            form=candidate.form_type,
            accession_number=candidate.accession_no,
        )
        if not filings:
            msg = f"No filing found for {candidate.ticker} {candidate.accession_no}"
            raise ValueError(msg)
        filing = filings[0]
        return _build_raw_filing_from_edgar(filing, candidate.ticker)


class FakeFilingSource(FilingSource):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._fixture = json.loads(settings.fixture_path.read_text(encoding="utf-8"))

    def list_candidates(self, ticker: str, form_types: list[str]) -> list[FilingCandidate]:
        if self._fixture.get("ticker", "").upper() != ticker.upper():
            return []
        allowed_forms = {form.upper() for form in form_types}
        if "candidates" in self._fixture:
            return [
                FilingCandidate.model_validate(item)
                for item in self._fixture["candidates"]
                if item["form_type"].upper() in allowed_forms
            ]
        candidate = FilingCandidate(
            ticker=self._fixture["ticker"],
            company=self._fixture["company"],
            cik=self._fixture["cik"],
            form_type=self._fixture["form_type"],
            fiscal_period=self._fixture["fiscal_period"],
            filing_date=self._fixture["filing_date"],
            accession_no=self._fixture["accession_no"],
            source_url=self._fixture["source_url"],
        )
        if candidate.form_type.upper() not in allowed_forms:
            return []
        return [candidate]

    def fetch_filing(self, candidate: FilingCandidate) -> RawFiling:
        if "filings" in self._fixture:
            data = self._fixture["filings"][candidate.accession_no]
        else:
            data = self._fixture
        sections = [RawSectionPayload.model_validate(section) for section in data["sections"]]
        return RawFiling(
            ticker=candidate.ticker,
            company=candidate.company,
            cik=candidate.cik,
            form_type=candidate.form_type,
            fiscal_period=candidate.fiscal_period,
            filing_date=candidate.filing_date,
            accession_no=candidate.accession_no,
            source_url=candidate.source_url,
            full_text=data["full_text"],
            sections=sections,
        )


def get_filing_source(settings: Settings | None = None) -> FilingSource:
    settings = settings or get_settings()
    backends: dict[str, type[FilingSource]] = {
        "edgar": EdgarFilingSource,
        "fake": FakeFilingSource,
    }
    backend = settings.filing_source
    try:
        impl = backends[backend]
    except KeyError as exc:
        raise ValueError(
            f"Unknown filing_source={backend!r}. Choose from: {sorted(backends)}"
        ) from exc
    return impl(settings)


def _fiscal_period_from_filing(filing) -> str:
    for attr in ("period_of_report", "report_date"):
        try:
            value = getattr(filing, attr, None)
            if callable(value):
                value = value()
        except Exception:
            value = None
        if value:
            return str(value)
    try:
        header = filing.header
        if header and header.period_of_report:
            return str(header.period_of_report)
    except Exception:
        pass
    return str(filing.filing_date)


def _build_raw_filing_from_edgar(filing, ticker: str) -> RawFiling:
    report = filing.obj()
    document = report.document
    full_text = clean_text(document.text())
    fiscal_period = _fiscal_period_from_filing(filing)
    sections: list[RawSectionPayload] = []

    for item_name in report.items:
        section_obj = document.sections.get_item(item_name)
        if section_obj is None:
            section_text = report[item_name]
            if not section_text:
                logger.warning("%s: section %s not found", ticker, item_name)
                continue
            section_obj = None
            raw_text = clean_text(str(section_text))
            section_start = full_text.find(raw_text[: min(200, len(raw_text))])
            section_end = section_start + len(raw_text) if section_start >= 0 else None
            tables: list[RawTablePayload] = []
        else:
            raw_text = clean_text(section_obj.text())
            section_start = section_obj.start_offset
            section_end = section_obj.end_offset
            tables = _extract_tables(section_obj, item_name, full_text, section_start)

        if not raw_text and not tables:
            logger.warning("%s: empty section %s", ticker, item_name)
            continue

        sections.append(
            RawSectionPayload(
                item=item_name,
                title=getattr(section_obj, "title", None) if section_obj else None,
                text=raw_text,
                tables=tables,
                section_char_start=section_start if section_start is not None else None,
                section_char_end=section_end if section_end is not None else None,
            )
        )

    return RawFiling(
        ticker=ticker.upper(),
        company=str(filing.company),
        cik=str(filing.cik),
        form_type=str(filing.form),
        fiscal_period=fiscal_period,
        filing_date=str(filing.filing_date),
        accession_no=str(filing.accession_no),
        source_url=str(filing.homepage_url),
        full_text=full_text,
        sections=sections,
    )


def _extract_tables(
    section_obj,
    item_name: str,
    full_text: str,
    section_hint: int,
) -> list[RawTablePayload]:
    tables: list[RawTablePayload] = []
    for index, table_node in enumerate(section_obj.tables()):
        linearized = clean_text(table_node.text())
        if not linearized:
            continue
        headers, rows = parse_linearized_table(linearized)
        summary = build_table_summary(item_name, headers, rows)
        char_start, char_end = _locate_in_document(full_text, linearized, section_hint)
        tables.append(
            RawTablePayload(
                table_id=f"{item_name.replace(' ', '_').lower()}-table-{index}",
                headers=headers,
                rows=rows,
                linearized=linearized,
                summary=summary,
                char_start=char_start,
                char_end=char_end,
            )
        )
    return tables


def _locate_in_document(full_text: str, needle: str, hint_start: int) -> tuple[int, int]:
    if not needle:
        return hint_start, hint_start
    pos = full_text.find(needle, max(0, hint_start))
    if pos < 0:
        pos = max(0, hint_start)
    return pos, pos + len(needle)


def filter_original_form_candidates(candidates: list[FilingCandidate]) -> list[FilingCandidate]:
    """MVP: exclude amendments (e.g. 10-K/A). Partial-amendment merge is v1."""
    return [candidate for candidate in candidates if not candidate.form_type.upper().endswith("/A")]


def select_filing_candidate(candidates: list[FilingCandidate]) -> FilingCandidate | None:
    """Pick the latest original filing for a ticker (MVP — no 10-K/A)."""
    originals = filter_original_form_candidates(candidates)
    if not originals:
        return None
    selected = dedupe_candidates(originals)
    return selected[0] if selected else None

