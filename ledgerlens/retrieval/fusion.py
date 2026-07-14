"""Reciprocal Rank Fusion — pure function, no I/O."""

from __future__ import annotations


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Fuse ranked id lists with RRF.

    Score for each id is ``sum(1 / (k + rank))`` across lists where it appears.
    ``rank`` is 1-based position within each leg. Returns ``(id, score)`` pairs
    sorted by fused score descending (ties broken by id for determinism).
    """
    if k < 1:
        raise ValueError(f"rrf k must be >= 1, got {k}")

    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
