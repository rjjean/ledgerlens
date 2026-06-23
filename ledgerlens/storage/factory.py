"""Factory for ChunkStore implementations."""

from ledgerlens.config import get_settings
from ledgerlens.storage.fake import FakeChunkStore
from ledgerlens.storage.postgres import PostgresChunkStore
from ledgerlens.storage.store import ChunkStore

_STORE_BACKENDS: dict[str, type[ChunkStore]] = {
    "fake": FakeChunkStore,
    "postgres": PostgresChunkStore,
}


def get_chunk_store() -> ChunkStore:
    settings = get_settings()
    backend = settings.storage_backend
    try:
        impl = _STORE_BACKENDS[backend]
    except KeyError as exc:
        raise ValueError(
            f"Unknown storage_backend={backend!r}. "
            f"Choose from: {sorted(_STORE_BACKENDS)}"
        ) from exc
    return impl(settings)
