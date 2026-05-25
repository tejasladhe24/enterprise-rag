from enterprise_rag.lib.db import Chunk as DbChunk


def reciprocal_rank_fusion(
    *ranked_lists: list[DbChunk],
    rrf_k: int = 60,
    top_n: int = 10,
) -> list[DbChunk]:
    scores: dict[int, float] = {}
    chunks_by_id: dict[int, DbChunk] = {}

    for results in ranked_lists:
        for rank, chunk in enumerate(results):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (rrf_k + rank + 1)
            chunks_by_id[chunk.id] = chunk

    if not scores:
        return []

    ordered_ids = sorted(scores, key=scores.get, reverse=True)
    return [chunks_by_id[chunk_id] for chunk_id in ordered_ids[:top_n]]
