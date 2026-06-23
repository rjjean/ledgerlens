"""Storage seam — Neon Postgres + pgvector behind ChunkStore."""

from ledgerlens.storage.factory import get_chunk_store
from ledgerlens.storage.store import ChunkStore

__all__ = ["ChunkStore", "get_chunk_store"]
