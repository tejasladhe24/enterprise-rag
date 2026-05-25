from __future__ import annotations

import threading
from typing import Any

from rerankers import Document
from rerankers import Reranker as create_reranker

from enterprise_rag.lib.db import Chunk as DbChunk
from enterprise_rag.utils.settings import settings

_reranker: Any | None = None
_lock = threading.Lock()


def get_reranker() -> Any:
    global _reranker
    if _reranker is None:
        with _lock:
            if _reranker is None:
                _reranker = create_reranker("cross-encoder")
    return _reranker


def rerank_chunks(
    query: str,
    chunks: list[DbChunk],
    top_k: int | None = None,
) -> list[DbChunk]:
    if not chunks:
        return []

    limit = top_k or settings.SEARCH_RESULT_K
    docs = [Document(text=chunk.text, doc_id=str(chunk.id)) for chunk in chunks]
    ranked = get_reranker().rank(query, docs).top_k(limit)

    by_id = {str(chunk.id): chunk for chunk in chunks}
    return [by_id[doc.doc_id] for doc in ranked if doc.doc_id in by_id]
