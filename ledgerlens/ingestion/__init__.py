"""Ingestion pipeline — edgartools download, section extract, structure-aware chunk."""

from ledgerlens.ingestion.pipeline import run_ingestion
from ledgerlens.ingestion.sources import get_filing_source

__all__ = ["get_filing_source", "run_ingestion"]
