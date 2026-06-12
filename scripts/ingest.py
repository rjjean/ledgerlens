"""One-shot Phase 1 ingestion script."""

from __future__ import annotations

import argparse
import sys

from ledgerlens.config import MVP_TICKERS, VALIDATE_FIRST_TICKERS, get_settings
from ledgerlens.ingestion.pipeline import run_ingestion


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest SEC 10-K filings and write chunks to disk.")
    parser.add_argument(
        "--tickers",
        type=str,
        default=",".join(VALIDATE_FIRST_TICKERS),
        help="Comma-separated tickers (default: MSFT,SNOW,NVDA validate-first subset).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=f"Ingest all {len(MVP_TICKERS)} locked MVP tickers.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()

    if args.all:
        tickers = list(settings.tickers)
    else:
        tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]

    print(f"Ingesting {len(tickers)} ticker(s): {', '.join(tickers)}")
    report = run_ingestion(tickers, settings=settings)
    if report.succeeded == 0:
        print("No filings succeeded — check logs and quality report.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
