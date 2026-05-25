import time
from dataclasses import dataclass

from enterprise_rag.cache.queries import cache_query_results, get_cached_query_results
from enterprise_rag.lib.db import Chunk as DbChunk
from enterprise_rag.lib.embeddings import embed_text
from enterprise_rag.search.executor import submit
from enterprise_rag.search.fusion import reciprocal_rank_fusion
from enterprise_rag.search.reranking import rerank_chunks
from enterprise_rag.search.retrieval import merge_chunks_by_id, search_keyword, search_vector
from enterprise_rag.utils.logger import logger
from enterprise_rag.utils.settings import settings


@dataclass(frozen=True)
class RetrievalResult:
    vector: list[DbChunk]
    keyword: list[DbChunk]

    @property
    def is_empty(self) -> bool:
        return not self.vector and not self.keyword


@dataclass
class SearchTimings:
    cache_lookup_ms: float = 0.0
    embed_ms: float = 0.0
    keyword_fts_ms: float = 0.0
    parallel_retrieval_ms: float = 0.0
    vector_ms: float = 0.0
    fusion_ms: float = 0.0
    cache_write_ms: float = 0.0
    total_ms: float = 0.0
    cache_hit: bool = False
    fusion_mode: str | None = None

    def as_log_kwargs(self) -> dict[str, float | bool | str | None]:
        return {
            "cache_lookup_ms": round(self.cache_lookup_ms, 2),
            "embed_ms": round(self.embed_ms, 2),
            "keyword_fts_ms": round(self.keyword_fts_ms, 2),
            "parallel_retrieval_ms": round(self.parallel_retrieval_ms, 2),
            "vector_ms": round(self.vector_ms, 2),
            "fusion_ms": round(self.fusion_ms, 2),
            "cache_write_ms": round(self.cache_write_ms, 2),
            "total_ms": round(self.total_ms, 2),
            "cache_hit": self.cache_hit,
            "fusion_mode": self.fusion_mode,
        }


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _log_search(
    query: str,
    timings: SearchTimings,
    *,
    result_count: int,
    vector_count: int = 0,
    keyword_count: int = 0,
) -> None:
    logger.info(
        "search_pipeline_completed",
        query=query,
        result_count=result_count,
        vector_count=vector_count,
        keyword_count=keyword_count,
        rerank_enabled=settings.SEARCH_ENABLE_RERANK,
        **timings.as_log_kwargs(),
    )


def _retrieve(
    embedding: list[float] | None,
    keyword: list[DbChunk],
    timings: SearchTimings,
) -> RetrievalResult:
    vector: list[DbChunk] = []
    if embedding:
        vector_start = time.perf_counter()
        vector = submit(search_vector, embedding, settings.SEARCH_VECTOR_K).result()
        timings.vector_ms = _elapsed_ms(vector_start)
    return RetrievalResult(vector=vector, keyword=keyword)


def _fuse_results(
    query: str,
    retrieval: RetrievalResult,
    timings: SearchTimings,
) -> list[DbChunk]:
    fusion_start = time.perf_counter()
    try:
        if settings.SEARCH_ENABLE_RERANK:
            timings.fusion_mode = "rerank"
            candidates = merge_chunks_by_id(retrieval.vector, retrieval.keyword)
            return rerank_chunks(query, candidates)

        timings.fusion_mode = "rrf"
        return reciprocal_rank_fusion(
            retrieval.vector,
            retrieval.keyword,
            rrf_k=settings.SEARCH_RRF_K,
            top_n=settings.SEARCH_RESULT_K,
        )
    finally:
        timings.fusion_ms = _elapsed_ms(fusion_start)


def search_pipeline(query: str) -> list[DbChunk]:
    total_start = time.perf_counter()
    timings = SearchTimings()

    cache_start = time.perf_counter()
    cached = get_cached_query_results(query)
    timings.cache_lookup_ms = _elapsed_ms(cache_start)

    if cached is not None:
        timings.cache_hit = True
        timings.total_ms = _elapsed_ms(total_start)
        _log_search(query, timings, result_count=len(cached))
        return cached

    parallel_start = time.perf_counter()
    embedding_future = submit(embed_text, query)
    keyword_future = submit(search_keyword, query, settings.SEARCH_FTS_K)

    embed_wait_start = time.perf_counter()
    embedding = embedding_future.result()
    timings.embed_ms = _elapsed_ms(embed_wait_start)

    keyword_wait_start = time.perf_counter()
    keyword_chunks = keyword_future.result()
    timings.keyword_fts_ms = _elapsed_ms(keyword_wait_start)
    timings.parallel_retrieval_ms = _elapsed_ms(parallel_start)

    retrieval = _retrieve(embedding, keyword_chunks, timings)
    if retrieval.is_empty:
        timings.total_ms = _elapsed_ms(total_start)
        _log_search(
            query,
            timings,
            result_count=0,
            vector_count=0,
            keyword_count=len(keyword_chunks),
        )
        return []

    results = _fuse_results(query, retrieval, timings)

    cache_write_start = time.perf_counter()
    cache_query_results(query, results)
    timings.cache_write_ms = _elapsed_ms(cache_write_start)

    timings.total_ms = _elapsed_ms(total_start)
    _log_search(
        query,
        timings,
        result_count=len(results),
        vector_count=len(retrieval.vector),
        keyword_count=len(retrieval.keyword),
    )
    return results
