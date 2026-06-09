"""Factory for seam implementations — backend selection is a config change."""

from ledgerlens.config import get_settings
from ledgerlens.interfaces.embedder import Embedder, FakeEmbedder, VoyageEmbedder
from ledgerlens.interfaces.llm import FakeLLM, LLMClient, LiteLLMClient
from ledgerlens.interfaces.reranker import CrossEncoderReranker, FakeReranker, Reranker

_EMBEDDER_BACKENDS: dict[str, type[Embedder]] = {
    "fake": FakeEmbedder,
    "voyage": VoyageEmbedder,
}

_RERANKER_BACKENDS: dict[str, type[Reranker]] = {
    "fake": FakeReranker,
    "cross_encoder": CrossEncoderReranker,
}

_LLM_BACKENDS: dict[str, type[LLMClient]] = {
    "fake": FakeLLM,
    "litellm": LiteLLMClient,
}


def get_embedder() -> Embedder:
    settings = get_settings()
    backend = settings.embedder_backend
    try:
        impl = _EMBEDDER_BACKENDS[backend]
    except KeyError as exc:
        raise ValueError(
            f"Unknown embedder_backend={backend!r}. "
            f"Choose from: {sorted(_EMBEDDER_BACKENDS)}"
        ) from exc
    return impl(settings)


def get_reranker() -> Reranker:
    settings = get_settings()
    backend = settings.reranker_backend
    try:
        impl = _RERANKER_BACKENDS[backend]
    except KeyError as exc:
        raise ValueError(
            f"Unknown reranker_backend={backend!r}. "
            f"Choose from: {sorted(_RERANKER_BACKENDS)}"
        ) from exc
    return impl(settings)


def get_llm() -> LLMClient:
    settings = get_settings()
    backend = settings.llm_backend
    try:
        impl = _LLM_BACKENDS[backend]
    except KeyError as exc:
        raise ValueError(
            f"Unknown llm_backend={backend!r}. Choose from: {sorted(_LLM_BACKENDS)}"
        ) from exc
    return impl(settings)
