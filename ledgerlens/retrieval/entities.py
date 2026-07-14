"""Static company alias → ticker resolution for retrieval pre-filtering."""

from __future__ import annotations

import re

from ledgerlens.config import MVP_TICKERS

# Hand-maintained aliases for the locked 18-ticker MVP corpus.
# Keys are lowercase; multi-word phrases are matched before single tokens.
COMPANY_ALIASES: dict[str, str] = {
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "palo alto networks": "PANW",
    "palo alto": "PANW",
    "servicenow": "NOW",
    "service now": "NOW",
    "meta": "META",
    "facebook": "META",
    "salesforce": "CRM",
    "broadcom": "AVGO",
    "workday": "WDAY",
    "mongodb": "MDB",
    "mongo db": "MDB",
    "crowdstrike": "CRWD",
    "crowd strike": "CRWD",
    "datadog": "DDOG",
    "data dog": "DDOG",
    "intuit": "INTU",
    "snowflake": "SNOW",
    "oracle": "ORCL",
    "adobe": "ADBE",
    "nvidia": "NVDA",
    "microsoft": "MSFT",
    "apple": "AAPL",
    "amd": "AMD",
    "advanced micro devices": "AMD",
}

# Bare tickers that are also common English words — only match when spelled
# exactly as the ticker (all-caps), or via a longer alias above.
_AMBIGUOUS_BARE_TICKERS = frozenset({"NOW"})

_ALIAS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(rf"(?i)\b{re.escape(alias)}\b"),
        ticker,
    )
    for alias, ticker in sorted(COMPANY_ALIASES.items(), key=lambda item: -len(item[0]))
]

_BARE_TICKER_PATTERNS: list[tuple[re.Pattern[str], str, bool]] = []
for _ticker in sorted(MVP_TICKERS, key=len, reverse=True):
    if _ticker in _AMBIGUOUS_BARE_TICKERS:
        # Case-sensitive: "now" must not resolve to ServiceNow.
        _BARE_TICKER_PATTERNS.append(
            (re.compile(rf"\b{re.escape(_ticker)}\b"), _ticker, False)
        )
    else:
        _BARE_TICKER_PATTERNS.append(
            (re.compile(rf"(?i)\b{re.escape(_ticker)}\b"), _ticker, True)
        )


def resolve_ticker(query: str) -> str | None:
    """Return the single corpus ticker named in ``query``, or None.

    Uses case-insensitive word-boundary matching over aliases and bare tickers.
    Returns None when zero or more than one distinct ticker is detected —
    ambiguity means no filter.
    """
    if not query or not query.strip():
        return None

    found: set[str] = set()
    for pattern, ticker in _ALIAS_PATTERNS:
        if pattern.search(query):
            found.add(ticker)

    for pattern, ticker, _case_insensitive in _BARE_TICKER_PATTERNS:
        if pattern.search(query):
            found.add(ticker)

    if len(found) == 1:
        return next(iter(found))
    return None
