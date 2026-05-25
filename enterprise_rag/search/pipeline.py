import concurrent.futures

from enterprise_rag.cache.queries import cache_query_results, get_cached_query_results
from enterprise_rag.lib.db import Chunk as DbChunk
from enterprise_rag.lib.embeddings import embed_text
from enterprise_rag.search.keyword import search_chunks_by_fts
from enterprise_rag.search.reranking import rerank_chunks
from enterprise_rag.search.vector import search_chunks_by_pgvector


def search_pipeline(query: str) -> list[DbChunk]:
    cached_results = get_cached_query_results(query)
    if cached_results:
        return cached_results

    query_embedding = embed_text(query)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_vector = executor.submit(
            search_chunks_by_pgvector,
            query_embedding or [],
            10,
        )
        future_keyword = executor.submit(search_chunks_by_fts, query, 10)
        vector_chunks = future_vector.result()
        keyword_chunks = future_keyword.result()

        merged_by_id = {chunk.id: chunk for chunk in vector_chunks + keyword_chunks}
        reranked_chunks = rerank_chunks(query, list(merged_by_id.values()))

    cache_query_results(query, reranked_chunks, expires_in=60 * 15)
    return reranked_chunks
