"""Phase 0 done-when gate — exercises fake seams via the factory."""

from __future__ import annotations

import sys

from ledgerlens.config import get_settings
from ledgerlens.interfaces.factory import get_embedder, get_llm, get_reranker


def main() -> int:
    settings = get_settings()
    embedder = get_embedder()
    reranker = get_reranker()
    llm = get_llm()

    assert embedder.model_name == settings.embedder_model
    assert embedder.dimensions == settings.embedder_dimensions

    docs = ["Revenue grew 12% year over year.", "Risk factors include supply chain disruption."]
    query = "What drove revenue growth?"

    doc_vectors = embedder.embed_documents(docs)
    query_vector = embedder.embed_query(query)

    assert len(doc_vectors) == len(docs)
    assert all(len(v) == embedder.dimensions for v in doc_vectors)
    assert len(query_vector) == embedder.dimensions
    assert doc_vectors[0] != query_vector

    ranked = reranker.rerank(query, docs, top_k=2)
    assert len(ranked) == 2
    assert ranked[0].index == 0
    assert ranked[0].score >= ranked[1].score

    response = llm.generate(
        system="Answer only from provided context.",
        messages=[{"role": "user", "content": query}],
    )
    assert isinstance(response.text, str) and response.text
    assert response.model == settings.llm_model

    print("Phase 0 plumbing is GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
