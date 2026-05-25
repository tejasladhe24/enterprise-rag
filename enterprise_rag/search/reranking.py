from rerankers import Document, Reranker

from enterprise_rag.lib.db import Chunk as DbChunk


def rerank_chunks(query: str, chunks: list[DbChunk]) -> list[DbChunk]:
    if not chunks:
        return []

    reranker = Reranker("cross-encoder")
    docs = [Document(text=chunk.text, doc_id=str(chunk.id)) for chunk in chunks]
    ranked = reranker.rank(query, docs).top_k(10)

    chunk_by_id = {str(chunk.id): chunk for chunk in chunks}
    return [chunk_by_id[doc.doc_id] for doc in ranked if doc.doc_id in chunk_by_id]
