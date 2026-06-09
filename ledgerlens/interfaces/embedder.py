"""Embedder seam — document vs query encoding kept separate."""

import hashlib
import struct
from abc import ABC, abstractmethod

from ledgerlens.config import Settings, get_settings


class Embedder(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @property
    @abstractmethod
    def dimensions(self) -> int: ...

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]: ...


def _deterministic_vector(text: str, dimensions: int, *, salt: str) -> list[float]:
    """Hash-based pseudo-embedding for the fake backend (deterministic, no SDK)."""
    digest = hashlib.sha256(f"{salt}:{text}".encode()).digest()
    values: list[float] = []
    counter = 0
    while len(values) < dimensions:
        block = hashlib.sha256(digest + counter.to_bytes(4, "big")).digest()
        for i in range(0, len(block), 4):
            if len(values) >= dimensions:
                break
            (raw,) = struct.unpack(">I", block[i : i + 4])
            values.append((raw / 2**32) * 2 - 1)
        counter += 1
    return values


class FakeEmbedder(Embedder):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def model_name(self) -> str:
        return self._settings.embedder_model

    @property
    def dimensions(self) -> int:
        return self._settings.embedder_dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [_deterministic_vector(t, self.dimensions, salt="doc") for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return _deterministic_vector(text, self.dimensions, salt="query")


class VoyageEmbedder(Embedder):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def model_name(self) -> str:
        return self._settings.embedder_model

    @property
    def dimensions(self) -> int:
        return self._settings.embedder_dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        client = self._client()
        result = client.embed(texts, model=self.model_name, input_type="document")
        return result.embeddings

    def embed_query(self, text: str) -> list[float]:
        client = self._client()
        result = client.embed([text], model=self.model_name, input_type="query")
        return result.embeddings[0]

    def _client(self):
        import voyageai  # noqa: PLC0415 — lazy import per seam pattern

        api_key = self._settings.voyage_api_key
        if not api_key:
            raise ValueError("VOYAGE_API_KEY is required when embedder_backend=voyage")
        return voyageai.Client(api_key=api_key)
