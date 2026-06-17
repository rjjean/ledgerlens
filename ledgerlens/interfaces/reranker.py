"""Reranker seam - cross-encoder over fused retrieval candidates."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ledgerlens.config import Settings, get_settings


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float


class Reranker(ABC):
    @abstractmethod
    def rerank(self, query: str, documents: list[str], top_k: int) -> list[RerankResult]: ...


class FakeReranker(Reranker):
    """Preserves input order with descending placeholder scores."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def rerank(self, query: str, documents: list[str], top_k: int) -> list[RerankResult]:
        del query  # unused in fake backend
        k = min(top_k, len(documents))
        return [RerankResult(index=i, score=float(len(documents) - i)) for i in range(k)]


class CrossEncoderReranker(Reranker):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._model = None

    def rerank(self, query: str, documents: list[str], top_k: int) -> list[RerankResult]:
        if not documents:
            return []

        model = self._get_model()
        pairs = [[query, doc] for doc in documents]
        scores = model.predict(pairs)

        ranked = sorted(
            (RerankResult(index=i, score=float(score)) for i, score in enumerate(scores)),
            key=lambda r: r.score,
            reverse=True,
        )
        return ranked[:top_k]

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder  # noqa: PLC0415

            self._model = CrossEncoder(self._settings.reranker_model)
        return self._model
