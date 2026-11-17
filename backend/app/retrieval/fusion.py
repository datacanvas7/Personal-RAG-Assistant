"""Reciprocal Rank Fusion: merge several ranked lists into one.

Vector search ranks by cosine similarity (a number between -1 and 1); keyword search ranks
by ``ts_rank_cd`` (an unbounded number on a different scale). Their scores cannot be added
or compared, but their *positions* can. RRF gives each list's n-th result the weight
``1 / (k + n)`` and sums the weights per chunk, so a chunk that both lists rank highly wins
and nothing needs normalising or tuning. ``k = 60`` is the value from the original paper
(Cormack et al., 2009) and is rarely worth changing.
"""

import uuid
from collections.abc import Sequence

from app.retrieval.vector_store import ScoredChunk

RRF_K = 60


def fuse_rrf(rankings: Sequence[Sequence[ScoredChunk]], *, k: int = RRF_K) -> list[ScoredChunk]:
    """One list ordered by summed reciprocal rank; each chunk keeps its cosine ``score``.

    Ties are broken by cosine score and then by chunk id, so the order is deterministic.
    """
    fused: dict[uuid.UUID, float] = {}
    chunks: dict[uuid.UUID, ScoredChunk] = {}
    for ranking in rankings:
        for position, chunk in enumerate(ranking, start=1):
            fused[chunk.chunk_id] = fused.get(chunk.chunk_id, 0.0) + 1.0 / (k + position)
            chunks.setdefault(chunk.chunk_id, chunk)
    order = sorted(fused, key=lambda cid: (-fused[cid], -chunks[cid].score, str(cid)))
    return [chunks[cid] for cid in order]
