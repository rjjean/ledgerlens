"""Pytest mirror of scripts/smoke_test.py — shapes, determinism, ordering."""

from ledgerlens.config import get_settings
from ledgerlens.interfaces.embedder import FakeEmbedder
from ledgerlens.interfaces.factory import get_embedder, get_llm, get_reranker
from ledgerlens.interfaces.llm import FakeLLM
from ledgerlens.interfaces.reranker import FakeReranker


def test_factory_returns_fake_backends_by_default():
    settings = get_settings()
    assert settings.embedder_backend == "fake"
    assert settings.reranker_backend == "fake"
    assert settings.llm_backend == "fake"

    embedder = get_embedder()
    reranker = get_reranker()
    llm = get_llm()

    assert isinstance(embedder, FakeEmbedder)
    assert isinstance(reranker, FakeReranker)
    assert isinstance(llm, FakeLLM)


def test_embedder_dimensions_from_config():
    settings = get_settings()
    embedder = FakeEmbedder(settings)
    assert embedder.dimensions == settings.embedder_dimensions

    text = "Operating margin improved in fiscal 2025."
    v1 = embedder.embed_query(text)
    v2 = embedder.embed_query(text)
    assert len(v1) == settings.embedder_dimensions
    assert v1 == v2

    doc_vecs = embedder.embed_documents([text, "Other passage."])
    assert len(doc_vecs) == 2
    assert all(len(v) == settings.embedder_dimensions for v in doc_vecs)
    assert doc_vecs[0] != v1  # document vs query salt


def test_reranker_identity_order_descending_scores():
    reranker = FakeReranker()
    docs = ["a", "b", "c"]
    ranked = reranker.rerank("query", docs, top_k=3)
    assert [r.index for r in ranked] == [0, 1, 2]
    assert ranked[0].score >= ranked[1].score >= ranked[2].score


def test_fake_llm_abstains():
    llm = FakeLLM()
    response = llm.generate(
        system="sys",
        messages=[{"role": "user", "content": "What is revenue?"}],
    )
    assert "don't have sufficient" in response.text.lower()
    assert response.usage is not None
    assert response.usage.output_tokens == 0
