"""One-shot Phase 2 embed + store script."""

from __future__ import annotations

import argparse
import sys

from ledgerlens.config import MVP_TICKERS, VALIDATE_FIRST_TICKERS, get_settings
from ledgerlens.storage.pipeline import ReconciliationError, run_embed_and_store


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Embed child/table chunks and upsert all chunks into the store."
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=",".join(VALIDATE_FIRST_TICKERS),
        help="Comma-separated tickers (default: MSFT,SNOW,NVDA validate-first subset).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=f"Embed and store all {len(MVP_TICKERS)} locked MVP tickers present in chunks.jsonl.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()

    if args.all:
        tickers = list(settings.tickers)
    else:
        tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]

    print(
        f"Embed + store for {len(tickers)} ticker(s): {', '.join(tickers)} "
        f"(embedder={settings.embedder_backend}, storage={settings.storage_backend})"
    )

    try:
        run_embed_and_store(tickers, settings=settings)
    except (ReconciliationError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
