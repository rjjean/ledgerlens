"""Offline hybrid retrieval tests (FakeEmbedder + FakeChunkStore + FakeReranker)."""

from __future__ import annotations

import os

import pytest

from ledgerlens.config import Settings
from ledgerlens.ingestion.models import ChunkRecord, ChunkType, Provenance
from ledgerlens.interfaces.embedder import FakeEmbedder
from ledgerlens.interfaces.reranker import FakeReranker
from ledgerlens.retrieval.fusion import reciprocal_rank_fusion
from ledgerlens.retrieval.retriever import HybridRetriever
from ledgerlens.storage.fake import FakeChunkStore


def _prov(
    ticker: str = "MSFT",
    section: str = "Item 1A",
    *,
    company: str | None = None,
) -> Provenance:
    return Provenance(
        company=company or f"{ticker} Corp",
        ticker=ticker,
        cik="0000000001",
        form_type="10-K",
        fiscal_period="FY2024",
        section=section,
        accession_no=f"000-{ticker}-24-000001",
        source_url=f"https://example.com/{ticker}",
        char_start=0,
        char_end=100,
    )


def _chunk(
    chunk_id: str,
    chunk_type: ChunkType,
    text: str,
    *,
    ticker: str = "MSFT",
    section: str = "Item 1A",
    parent_id: str | None = None,
    is_table: bool = False,
) -> ChunkRecord:
    return ChunkRecord(
        id=chunk_id,
        chunk_type=chunk_type,
        text=text,
        parent_id=parent_id,
        is_table=is_table,
        token_count=10,
        summary=None,
        table_data={"headers": ["A"], "rows": [["1"]]} if is_table else None,
        provenance=_prov(ticker=ticker, section=section),
    )


def _seed_store() -> FakeChunkStore:
    """Seed known vectors so dense ranking is deterministic offline."""
    store = FakeChunkStore()
    parent = _chunk("p-msft", ChunkType.PARENT, "Microsoft risk factors parent section.")
    child_msft = _chunk(
        "c-msft-risk",
        ChunkType.CHILD,
        "Microsoft faces cybersecurity and regulatory risk factors.",
        parent_id="p-msft",
    )
    child_nvda = _chunk(
        "c-nvda-risk",
        ChunkType.CHILD,
        "NVIDIA faces supply chain and competition risk factors.",
        ticker="NVDA",
        parent_id="p-msft",
    )
    table = _chunk(
        "t-msft-rev",
        ChunkType.TABLE,
        "Revenue | 2024\nCloud revenue grew year over year",
        section="Item 8",
        parent_id="p-msft",
        is_table=True,
    )
    # Near-orthogonal-ish canned vectors; query will be closest to c-msft-risk.
    embeddings = {
        "c-msft-risk": [1.0, 0.0, 0.0, 0.0],
        "c-nvda-risk": [0.0, 1.0, 0.0, 0.0],
        "t-msft-rev": [0.0, 0.0, 1.0, 0.0],
    }
    store.upsert_chunks([parent, child_msft, child_nvda, table], embeddings)
    return store


class _FixedQueryEmbedder(FakeEmbedder):
    """Returns a fixed query vector so dense search order is test-controlled."""

    def embed_query(self, text: str) -> list[float]:
        del text
        return [1.0, 0.0, 0.0, 0.0]


@pytest.fixture
def retrieval_settings() -> Settings:
    return Settings(
        embedder_backend="fake",
        reranker_backend="fake",
        storage_backend="fake",
        embedder_dimensions=4,
        rrf_k=60,
        dense_candidates=10,
        fts_candidates=10,
        rerank_candidates=10,
        retrieval_top_k=3,
        rerank_enabled=True,
    )


def test_rrf_prefers_chunk_in_both_legs():
    fused = reciprocal_rank_fusion(
        [
            ["both", "dense_only"],
            ["both", "fts_only"],
        ],
        k=60,
    )
    assert fused[0][0] == "both"
    scores = dict(fused)
    assert scores["both"] > scores["dense_only"]
    assert scores["both"] > scores["fts_only"]


def test_rrf_rank_math():
    fused = reciprocal_rank_fusion([["a", "b"]], k=60)
    assert fused == [("a", 1.0 / 61), ("b", 1.0 / 62)]


def test_dense_excludes_parents(retrieval_settings: Settings):
    store = _seed_store()
    hits = store.search_dense([1.0, 0.0, 0.0, 0.0], k=10)
    ids = [hit.chunk.id for hit in hits]
    assert "p-msft" not in ids
    assert all(hit.chunk.chunk_type != ChunkType.PARENT for hit in hits)
    assert ids[0] == "c-msft-risk"


def test_fts_excludes_parents(retrieval_settings: Settings):
    store = _seed_store()
    # Parent text also contains "risk factors"; without the embedding guard it
    # would be a legitimate FTS hit and pollute RRF.
    hits = store.search_fts("risk factors", k=10)
    assert hits
    assert all(hit.chunk.chunk_type != ChunkType.PARENT for hit in hits)
    assert "p-msft" not in {hit.chunk.id for hit in hits}


def test_fts_ranks_lexical_matches(retrieval_settings: Settings):
    store = _seed_store()
    hits = store.search_fts("cybersecurity regulatory", k=10)
    assert hits
    assert hits[0].chunk.id == "c-msft-risk"


def test_fts_or_semantics_on_natural_language_question(retrieval_settings: Settings):
    """Multi-word NL query must still return hits (OR lexemes, not AND-all-terms)."""
    store = _seed_store()
    hits = store.search_fts("What are NVIDIA's principal risk factors?", k=10)
    assert hits, "FTS returned no candidates for a natural-language question"
    assert any(hit.chunk.provenance.ticker == "NVDA" for hit in hits)
    assert all(hit.chunk.chunk_type != ChunkType.PARENT for hit in hits)


def test_filters_restrict_ticker(retrieval_settings: Settings):
    store = _seed_store()
    hits = store.search_fts("risk factors", k=10, filters={"ticker": "NVDA"})
    assert hits
    assert all(hit.chunk.provenance.ticker == "NVDA" for hit in hits)


def test_fetch_parent(retrieval_settings: Settings):
    store = _seed_store()
    parent = store.fetch_parent("p-msft")
    assert parent is not None
    assert parent.chunk_type == ChunkType.PARENT
    assert store.fetch_parent("c-msft-risk") is None
    assert store.fetch_parent("missing") is None


def test_retrieve_honors_top_k_and_provenance(retrieval_settings: Settings):
    store = _seed_store()
    retriever = HybridRetriever(
        settings=retrieval_settings,
        store=store,
        embedder=_FixedQueryEmbedder(retrieval_settings),
        reranker=FakeReranker(retrieval_settings),
    )
    results = retriever.retrieve("Microsoft cybersecurity risk factors", top_k=2)
    assert len(results) == 2
    assert results[0].rank == 1
    assert results[1].rank == 2
    for result in results:
        prov = result.chunk.provenance
        assert prov.ticker
        assert prov.section
        assert prov.accession_no
        assert prov.source_url
        assert result.rrf_score > 0


def test_retrieve_filter_excludes_other_tickers(retrieval_settings: Settings):
    store = _seed_store()
    retriever = HybridRetriever(
        settings=retrieval_settings,
        store=store,
        embedder=_FixedQueryEmbedder(retrieval_settings),
        reranker=FakeReranker(retrieval_settings),
    )
    results = retriever.retrieve(
        "risk factors",
        top_k=5,
        filters={"ticker": "NVDA"},
    )
    assert results
    assert all(r.chunk.provenance.ticker == "NVDA" for r in results)


def test_rerank_on_and_off_well_formed(retrieval_settings: Settings):
    store = _seed_store()
    retriever = HybridRetriever(
        settings=retrieval_settings,
        store=store,
        embedder=_FixedQueryEmbedder(retrieval_settings),
        reranker=FakeReranker(retrieval_settings),
    )
    on = retriever.retrieve("risk factors", top_k=2, rerank_enabled=True)
    off = retriever.retrieve("risk factors", top_k=2, rerank_enabled=False)
    assert len(on) == 2
    assert len(off) == 2
    assert all(r.rerank_score is not None for r in on)
    assert all(r.rerank_score is None for r in off)


def test_eval_excludes_negative_controls_from_recall(retrieval_settings: Settings):
    from scripts.eval_retrieval import EvalQuestion, ExpectedSource, evaluate

    store = _seed_store()
    retriever = HybridRetriever(
        settings=retrieval_settings,
        store=store,
        embedder=_FixedQueryEmbedder(retrieval_settings),
        reranker=FakeReranker(retrieval_settings),
    )
    questions = [
        EvalQuestion(
            id="q-scored",
            question="cybersecurity regulatory",
            expected=[ExpectedSource(ticker="MSFT", section="Item 1A")],
        ),
        EvalQuestion(
            id="q-neg",
            question="topic verified absent from corpus",
            expected=[],
        ),
    ]
    report = evaluate(retriever, questions, top_k=3, rerank_enabled=False)
    assert report["total"] == 1
    assert len(report["questions"]) == 1
    assert report["questions"][0]["id"] == "q-scored"
    assert "leg_stats" in report["questions"][0]
    assert set(report["metrics"].keys()) >= {
        "recall@1",
        "recall@3",
        "recall@5",
        "recall@10",
        "mrr",
        "hits",
    }
    assert len(report["negative_controls"]) == 1
    assert report["negative_controls"][0]["id"] == "q-neg"
    assert len(report["negative_controls"][0]["results"]) <= 3


def test_breadth_scoring_requires_distinct_tickers_in_section(retrieval_settings: Settings):
    from ledgerlens.retrieval.models import RetrievalResult
    from scripts.eval_retrieval import (
        ExpectedSource,
        SCORING_BREADTH,
        first_hit_rank,
        is_hit,
        load_fixture,
        recall_at_k,
    )

    def _hit(rank: int, ticker: str, section: str = "Item 1A") -> RetrievalResult:
        chunk = _chunk(f"c-{ticker}-{rank}", ChunkType.CHILD, f"{ticker} AI competition", ticker=ticker, section=section)
        return RetrievalResult(chunk=chunk, rank=rank, score=1.0, rrf_score=0.01)

    expected = [ExpectedSource(section="Item 1A")]
    # Exact mode would MISS without a listed ticker — breadth counts distinct Item 1A tickers.
    results = [
        _hit(1, "META"),
        _hit(2, "INTU"),
        _hit(3, "NOW"),
        _hit(4, "NVDA"),
    ]
    assert is_hit(results, expected, scoring=SCORING_BREADTH, min_tickers=3)
    assert not is_hit(results[:2], expected, scoring=SCORING_BREADTH, min_tickers=3)
    assert recall_at_k(results, expected, 3, scoring=SCORING_BREADTH, min_tickers=3)
    assert not recall_at_k(results, expected, 2, scoring=SCORING_BREADTH, min_tickers=3)
    assert first_hit_rank(results, expected, scoring=SCORING_BREADTH, min_tickers=3) == 3

    # Wrong section does not count toward breadth.
    wrong = [_hit(1, "META", "Item 7"), _hit(2, "INTU", "Item 7"), _hit(3, "NOW", "Item 7")]
    assert not is_hit(wrong, expected, scoring=SCORING_BREADTH, min_tickers=3)

    top_k, questions = load_fixture(retrieval_settings.retrieval_eval_path)
    assert top_k == 10
    q05 = next(q for q in questions if q.id == "q05")
    assert q05.scoring == SCORING_BREADTH
    assert q05.min_tickers == 3
    assert all(e.section == "Item 1A" for e in q05.expected)


def test_rerank_text_uses_full_table_linearization(retrieval_settings: Settings):
    from ledgerlens.retrieval.text import rerank_text_for_chunk

    table = _chunk(
        "t-legal",
        ChunkType.TABLE,
        text="short stub",
        section="Item 8",
        is_table=True,
    )
    table = table.model_copy(
        update={
            "table_data": {
                "headers": ["Proceeding", "Status"],
                "rows": [
                    ["US v. Alphabet", "ongoing"],
                    ["EU antitrust", "settled"],
                ],
            }
        }
    )
    text = rerank_text_for_chunk(table)
    assert "US v. Alphabet" in text
    assert "EU antitrust" in text
    assert len(text) > len("short stub")


def test_retrieve_with_stats_reports_leg_counts(retrieval_settings: Settings):
    store = _seed_store()
    retriever = HybridRetriever(
        settings=retrieval_settings,
        store=store,
        embedder=_FixedQueryEmbedder(retrieval_settings),
        reranker=FakeReranker(retrieval_settings),
    )
    _results, stats = retriever.retrieve_with_stats(
        "What are NVIDIA's principal risk factors?",
        top_k=3,
        rerank_enabled=False,
    )
    assert stats.dense_count >= 1
    assert stats.fts_count >= 1
    assert 0 <= stats.overlap_count <= min(stats.dense_count, stats.fts_count)


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
def test_postgres_dense_and_fts_integration():
    """Opt-in: 1024-d search_dense (<=> cast) + FTS against a live Postgres."""
    from ledgerlens.storage.postgres import PostgresChunkStore

    dim = 1024
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        embedder_backend="fake",
        storage_backend="postgres",
        embedder_dimensions=dim,
        fts_language="english",
    )
    store = PostgresChunkStore(settings)
    store.init_schema()

    def unit_vec(axis: int) -> list[float]:
        vec = [0.0] * dim
        vec[axis] = 1.0
        return vec

    parent = _chunk("p-int", ChunkType.PARENT, "Integration parent.")
    near = _chunk(
        "c-near",
        ChunkType.CHILD,
        "alpha cybersecurity regulatory lexical hit",
        parent_id="p-int",
    )
    far = _chunk(
        "c-far",
        ChunkType.CHILD,
        "unrelated renewable biomass language",
        parent_id="p-int",
        ticker="NVDA",
    )
    near_vec = unit_vec(0)
    far_vec = unit_vec(1)
    store.upsert_chunks(
        [parent, near, far],
        {"c-near": near_vec, "c-far": far_vec},
    )

    # Exact match on c-near → cosine distance 0; must rank first even vs full corpus.
    dense = store.search_dense(near_vec, k=5)
    assert dense, "search_dense returned no rows"
    dense_ids = [hit.chunk.id for hit in dense]
    assert "p-int" not in dense_ids
    assert dense_ids[0] == "c-near"
    assert dense[0].score == pytest.approx(0.0, abs=1e-6)
    if len(dense) > 1:
        assert dense[0].score <= dense[1].score

    fts = store.search_fts("cybersecurity regulatory", k=5)
    assert fts
    assert fts[0].chunk.id == "c-near"
    assert all(hit.chunk.chunk_type != ChunkType.PARENT for hit in fts)

    # OR semantics: NL question must still return candidates (not AND-all-terms).
    fts_nl = store.search_fts(
        "What are the principal cybersecurity regulatory factors?",
        k=5,
    )
    assert fts_nl, "FTS OR query returned no rows for a natural-language question"
    assert any(hit.chunk.id == "c-near" for hit in fts_nl)
