"""Phase 3 informal recall eval — scores retrieve() against Ryan's hand fixture.

Reads data/fixtures/retrieval_questions.json (or --fixture). Does not invent
questions. Runs twice (rerank on/off) and prints recall@k / MRR plus the delta.

Questions with ``"expected": []`` are negative controls: excluded from recall
aggregates and printed under a manual-inspection section (top-3 + scores).

Per-question ``"scoring"``: ``exact`` (default — any ticker+section match) or
``breadth`` (≥ ``min_tickers`` distinct tickers in the expected section).

Live usage (Ryan):
  STORAGE_BACKEND=postgres EMBEDDER_BACKEND=voyage \\
  RERANKER_BACKEND=cross_encoder python scripts/eval_retrieval.py
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ledgerlens.config import get_settings
from ledgerlens.retrieval.models import RetrievalResult
from ledgerlens.retrieval.retriever import HybridRetriever
from ledgerlens.retrieval.text import rerank_text_for_chunk

RECALL_CUTOFFS = (1, 3, 5, 10)
SCORING_EXACT = "exact"
SCORING_BREADTH = "breadth"
DEFAULT_BREADTH_MIN_TICKERS = 3


@dataclass(frozen=True)
class ExpectedSource:
    ticker: str | None = None
    section: str | None = None


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    question: str
    expected: list[ExpectedSource]
    scoring: str = SCORING_EXACT
    min_tickers: int = DEFAULT_BREADTH_MIN_TICKERS

    @property
    def is_negative_control(self) -> bool:
        return len(self.expected) == 0


def load_fixture(path: Path) -> tuple[int, list[EvalQuestion]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    top_k = int(payload.get("top_k", 10))
    questions: list[EvalQuestion] = []
    for raw in payload.get("questions", []):
        expected = [
            ExpectedSource(
                ticker=entry.get("ticker"),
                section=entry.get("section"),
            )
            for entry in raw.get("expected", [])
        ]
        scoring = str(raw.get("scoring", SCORING_EXACT)).lower()
        if scoring not in (SCORING_EXACT, SCORING_BREADTH):
            raise ValueError(
                f"Unknown scoring={scoring!r} for question {raw.get('id')!r}. "
                f"Use {SCORING_EXACT!r} or {SCORING_BREADTH!r}."
            )
        questions.append(
            EvalQuestion(
                id=str(raw["id"]),
                question=str(raw["question"]),
                expected=expected,
                scoring=scoring,
                min_tickers=int(raw.get("min_tickers", DEFAULT_BREADTH_MIN_TICKERS)),
            )
        )
    return top_k, questions


def _matches_expected(result: RetrievalResult, expected: ExpectedSource) -> bool:
    prov = result.chunk.provenance
    if expected.ticker is not None and prov.ticker != expected.ticker:
        return False
    if expected.section is not None and prov.section != expected.section:
        return False
    return expected.ticker is not None or expected.section is not None


def _breadth_section(expected: list[ExpectedSource]) -> str | None:
    sections = {e.section for e in expected if e.section}
    if len(sections) != 1:
        return None
    return next(iter(sections))


def _distinct_tickers_in_section(
    results: list[RetrievalResult],
    section: str,
) -> set[str]:
    return {
        r.chunk.provenance.ticker
        for r in results
        if r.chunk.provenance.section == section
    }


def is_breadth_hit(
    results: list[RetrievalResult],
    expected: list[ExpectedSource],
    min_tickers: int,
) -> bool:
    """Hit when ≥ min_tickers distinct tickers appear in the expected section."""
    section = _breadth_section(expected)
    if section is None or min_tickers < 1:
        return False
    return len(_distinct_tickers_in_section(results, section)) >= min_tickers


def first_breadth_hit_rank(
    results: list[RetrievalResult],
    expected: list[ExpectedSource],
    min_tickers: int,
) -> int | None:
    """Rank at which the result set first reaches min_tickers distinct section hits."""
    section = _breadth_section(expected)
    if section is None or min_tickers < 1:
        return None
    seen: set[str] = set()
    for result in results:
        if result.chunk.provenance.section != section:
            continue
        seen.add(result.chunk.provenance.ticker)
        if len(seen) >= min_tickers:
            return result.rank
    return None


def is_hit(
    results: list[RetrievalResult],
    expected: list[ExpectedSource],
    *,
    scoring: str = SCORING_EXACT,
    min_tickers: int = DEFAULT_BREADTH_MIN_TICKERS,
) -> bool:
    """Score a result list: exact ticker+section match, or breadth (≥N tickers in section)."""
    if not expected:
        return False
    if scoring == SCORING_BREADTH:
        return is_breadth_hit(results, expected, min_tickers)
    for result in results:
        for source in expected:
            if _matches_expected(result, source):
                return True
    return False


def first_hit_rank(
    results: list[RetrievalResult],
    expected: list[ExpectedSource],
    *,
    scoring: str = SCORING_EXACT,
    min_tickers: int = DEFAULT_BREADTH_MIN_TICKERS,
) -> int | None:
    """1-based rank of the first scoring hit, or None if no hit."""
    if not expected:
        return None
    if scoring == SCORING_BREADTH:
        return first_breadth_hit_rank(results, expected, min_tickers)
    for result in results:
        for source in expected:
            if _matches_expected(result, source):
                return result.rank
    return None


def recall_at_k(
    results: list[RetrievalResult],
    expected: list[ExpectedSource],
    k: int,
    *,
    scoring: str = SCORING_EXACT,
    min_tickers: int = DEFAULT_BREADTH_MIN_TICKERS,
) -> bool:
    return is_hit(
        results[:k],
        expected,
        scoring=scoring,
        min_tickers=min_tickers,
    )


def _serialize_results(results: list[RetrievalResult]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for r in results:
        rerank_body = rerank_text_for_chunk(r.chunk)
        serialized.append(
            {
                "rank": r.rank,
                "score": r.score,
                "rrf_score": r.rrf_score,
                "rerank_score": r.rerank_score,
                "ticker": r.chunk.provenance.ticker,
                "section": r.chunk.provenance.section,
                "accession_no": r.chunk.provenance.accession_no,
                "chunk_id": r.chunk.id,
                "chunk_type": str(r.chunk.chunk_type),
                "text_len": len(rerank_body),
                "dense_score": r.dense_score,
                "fts_score": r.fts_score,
            }
        )
    return serialized


def evaluate(
    retriever: HybridRetriever,
    questions: list[EvalQuestion],
    top_k: int,
    *,
    rerank_enabled: bool,
    ticker_filter_enabled: bool,
) -> dict[str, Any]:
    scored: list[dict[str, Any]] = []
    negative_controls: list[dict[str, Any]] = []
    cutoff_hits = {k: 0 for k in RECALL_CUTOFFS}
    reciprocal_ranks: list[float] = []

    for item in questions:
        results, leg_stats = retriever.retrieve_with_stats(
            item.question,
            top_k=top_k,
            rerank_enabled=rerank_enabled,
            ticker_filter_enabled=ticker_filter_enabled,
        )
        serialized = _serialize_results(results)
        leg_payload = {
            "dense": leg_stats.dense_count,
            "fts": leg_stats.fts_count,
            "overlap": leg_stats.overlap_count,
            "resolved_ticker": leg_stats.resolved_ticker,
            "ticker_filter_applied": leg_stats.ticker_filter_applied,
        }

        if item.is_negative_control:
            negative_controls.append(
                {
                    "id": item.id,
                    "question": item.question,
                    "leg_stats": leg_payload,
                    "results": serialized[:3],
                }
            )
            continue

        hit_at: dict[int, bool] = {
            k: recall_at_k(
                results,
                item.expected,
                k,
                scoring=item.scoring,
                min_tickers=item.min_tickers,
            )
            for k in RECALL_CUTOFFS
        }
        for k, hit in hit_at.items():
            if hit:
                cutoff_hits[k] += 1

        rank = first_hit_rank(
            results,
            item.expected,
            scoring=item.scoring,
            min_tickers=item.min_tickers,
        )
        reciprocal_ranks.append((1.0 / rank) if rank is not None else 0.0)

        scored.append(
            {
                "id": item.id,
                "question": item.question,
                "scoring": item.scoring,
                "hit": hit_at.get(top_k, hit_at[max(RECALL_CUTOFFS)]),
                "hit_at": hit_at,
                "first_hit_rank": rank,
                "leg_stats": leg_payload,
                "results": serialized,
            }
        )

    total = len(scored)
    metrics = {
        f"recall@{k}": (cutoff_hits[k] / total) if total else 0.0 for k in RECALL_CUTOFFS
    }
    metrics["mrr"] = (sum(reciprocal_ranks) / total) if total else 0.0
    metrics["hits"] = {k: cutoff_hits[k] for k in RECALL_CUTOFFS}
    return {
        "rerank_enabled": rerank_enabled,
        "ticker_filter_enabled": ticker_filter_enabled,
        "top_k": top_k,
        "total": total,
        "metrics": metrics,
        "hits": cutoff_hits.get(top_k, cutoff_hits[10]),
        "recall_at_k": metrics.get(f"recall@{top_k}", metrics["recall@10"]),
        "questions": scored,
        "negative_controls": negative_controls,
    }


def _format_hit_line(hit: dict[str, Any]) -> str:
    legs = []
    if hit.get("dense_score") is not None:
        legs.append(f"dense={hit['dense_score']:.4f}")
    if hit.get("fts_score") is not None:
        legs.append(f"fts={hit['fts_score']:.4f}")
    leg_s = ("  " + " ".join(legs)) if legs else ""
    line = (
        f"  #{hit['rank']}  {hit['ticker']}  {hit['section']}  "
        f"type={hit['chunk_type']}  text_len={hit['text_len']}  "
        f"acc={hit['accession_no']}  id={hit['chunk_id']}  "
        f"score={hit['score']:.4f}  rrf={hit['rrf_score']:.6f}"
        f"{leg_s}"
    )
    if hit["rerank_score"] is not None:
        line += f"  rerank={hit['rerank_score']:.4f}"
    return line


def _format_metrics(metrics: dict[str, Any]) -> str:
    parts = [f"recall@{k}={metrics[f'recall@{k}']:.3f}" for k in RECALL_CUTOFFS]
    parts.append(f"MRR={metrics['mrr']:.3f}")
    return "  ".join(parts)


def _print_run(label: str, report: dict[str, Any]) -> None:
    print(
        f"\n=== {label} "
        f"(ticker_filter={report['ticker_filter_enabled']}, "
        f"rerank={report['rerank_enabled']}) ==="
    )
    print(_format_metrics(report["metrics"]))
    hits = report["metrics"]["hits"]
    total = report["total"]
    print(
        "  "
        + "  ".join(f"hits@{k}={hits[k]}/{total}" for k in RECALL_CUTOFFS)
    )
    for item in report["questions"]:
        mark = "HIT " if item["hit"] else "MISS"
        leg = item["leg_stats"]
        scoring = item.get("scoring", SCORING_EXACT)
        resolved = leg.get("resolved_ticker")
        resolved_s = resolved if resolved else "none"
        applied = "yes" if leg.get("ticker_filter_applied") else "no"
        print(
            f"\n[{mark}] {item['id']}: {item['question']}\n"
            f"  scoring={scoring}  resolved_ticker={resolved_s}  "
            f"filter_applied={applied}\n"
            f"  legs: dense={leg['dense']}  fts={leg['fts']}  "
            f"overlap={leg['overlap']}  first_hit_rank={item['first_hit_rank']}"
        )
        for hit in item["results"]:
            print(_format_hit_line(hit))

    controls = report.get("negative_controls") or []
    if controls:
        print("\n--- Negative controls — manual inspection ---")
        for item in controls:
            leg = item["leg_stats"]
            resolved = leg.get("resolved_ticker")
            resolved_s = resolved if resolved else "none"
            print(
                f"\n[NEG ] {item['id']}: {item['question']}\n"
                f"  resolved_ticker={resolved_s}  "
                f"legs: dense={leg['dense']}  fts={leg['fts']}  "
                f"overlap={leg['overlap']}"
            )
            if not item["results"]:
                print("  (no results)")
                continue
            for hit in item["results"]:
                print(_format_hit_line(hit))


def _print_uplift_matrix(reports: dict[tuple[bool, bool], dict[str, Any]]) -> None:
    """Print 2×2 summary: ticker filter on/off × rerank on/off."""
    print("\n=== 2×2 summary (filter × rerank) ===")
    header = f"{'filter':<8} {'rerank':<8} " + "  ".join(
        f"{'R@'+str(k):>6}" for k in RECALL_CUTOFFS
    ) + f"  {'MRR':>6}"
    print(header)
    for filter_on in (False, True):
        for rerank_on in (False, True):
            report = reports[(filter_on, rerank_on)]
            m = report["metrics"]
            row = (
                f"{('ON' if filter_on else 'OFF'):<8} "
                f"{('ON' if rerank_on else 'OFF'):<8} "
                + "  ".join(f"{m[f'recall@{k}']:>6.3f}" for k in RECALL_CUTOFFS)
                + f"  {m['mrr']:>6.3f}"
            )
            print(row)

    print("\n=== deltas vs filter=OFF rerank=OFF ===")
    base = reports[(False, False)]["metrics"]
    for filter_on in (False, True):
        for rerank_on in (False, True):
            if (filter_on, rerank_on) == (False, False):
                continue
            m = reports[(filter_on, rerank_on)]["metrics"]
            parts = [
                f"R@{k}={m[f'recall@{k}'] - base[f'recall@{k}']:+.3f}"
                for k in RECALL_CUTOFFS
            ]
            parts.append(f"MRR={m['mrr'] - base['mrr']:+.3f}")
            print(
                f"  filter={'ON' if filter_on else 'OFF'} "
                f"rerank={'ON' if rerank_on else 'OFF'}: "
                + "  ".join(parts)
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Score HybridRetriever against the hand-authored recall fixture."
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=settings.retrieval_eval_path,
        help="Path to retrieval_questions.json (Ryan-authored).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Override fixture top_k.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    fixture_path: Path = args.fixture

    if not fixture_path.exists():
        print(f"Fixture not found: {fixture_path}", file=sys.stderr)
        return 1

    top_k, questions = load_fixture(fixture_path)
    if args.top_k is not None:
        top_k = args.top_k

    if not questions:
        print(
            f"No questions in {fixture_path}. "
            "Author the ~10 hand questions (id, question, expected ticker/section), "
            "then re-run.",
            file=sys.stderr,
        )
        return 2

    scored_n = sum(1 for q in questions if not q.is_negative_control)
    neg_n = sum(1 for q in questions if q.is_negative_control)
    print(
        f"Eval fixture={fixture_path}  questions={len(questions)} "
        f"(scored={scored_n}, negative_controls={neg_n})  top_k={top_k}  "
        f"embedder={settings.embedder_backend}  storage={settings.storage_backend}  "
        f"reranker={settings.reranker_backend}"
    )

    retriever = HybridRetriever(settings=settings)
    reports: dict[tuple[bool, bool], dict[str, Any]] = {}
    for filter_on in (False, True):
        for rerank_on in (False, True):
            label = (
                f"filter={'ON' if filter_on else 'OFF'} "
                f"rerank={'ON' if rerank_on else 'OFF'}"
            )
            report = evaluate(
                retriever,
                questions,
                top_k,
                rerank_enabled=rerank_on,
                ticker_filter_enabled=filter_on,
            )
            reports[(filter_on, rerank_on)] = report
            _print_run(label, report)

    _print_uplift_matrix(reports)
    return 0


if __name__ == "__main__":
    sys.exit(main())
