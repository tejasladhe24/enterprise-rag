import json
from typing import Any

from redis import Redis

from enterprise_rag.lib.db import Chunk as DbChunk
from enterprise_rag.utils.settings import settings

redis_client = Redis.from_url(f"{settings.REDIS_URL}/2")

_RESULTS_PREFIX = "search:results:"
_EMBED_PREFIX = "search:embed:"


def normalize_query(query: str) -> str:
    return " ".join(query.strip().lower().split())


def _results_key(query: str) -> str:
    return f"{_RESULTS_PREFIX}{normalize_query(query)}"


def _embed_key(query: str) -> str:
    return f"{_EMBED_PREFIX}{normalize_query(query)}"


def _get_json(key: str) -> Any | None:
    raw = redis_client.get(key)
    if not raw:
        return None
    return json.loads(raw)


def _set_json(key: str, value: Any, ttl: int) -> None:
    redis_client.set(key, json.dumps(value), ex=ttl)


def _chunk_to_dict(chunk: DbChunk) -> dict:
    return {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "text": chunk.text,
        "chunk_index": chunk.chunk_index,
        "token_count": chunk.token_count,
        "chunk_metadata": chunk.chunk_metadata,
    }


def _dict_to_chunk(data: dict) -> DbChunk:
    return DbChunk(
        id=data["id"],
        document_id=data["document_id"],
        text=data["text"],
        chunk_index=data["chunk_index"],
        token_count=data["token_count"],
        chunk_metadata=data.get("chunk_metadata"),
    )


def cache_query_results(
    query: str,
    chunks: list[DbChunk],
    expires_in: int = settings.SEARCH_CACHE_TTL_SECONDS,
) -> None:
    if not chunks or not normalize_query(query):
        return
    _set_json(
        _results_key(query),
        [_chunk_to_dict(chunk) for chunk in chunks],
        expires_in,
    )


def get_cached_query_results(query: str) -> list[DbChunk] | None:
    if not normalize_query(query):
        return None
    payload = _get_json(_results_key(query))
    if payload is None:
        return None
    return [_dict_to_chunk(item) for item in payload]


def cache_embedding(
    query: str,
    embedding: list[float],
    expires_in: int = settings.EMBEDDING_CACHE_TTL_SECONDS,
) -> None:
    if not normalize_query(query):
        return
    _set_json(_embed_key(query), embedding, expires_in)


def get_cached_embedding(query: str) -> list[float] | None:
    if not normalize_query(query):
        return None
    payload = _get_json(_embed_key(query))
    return payload if isinstance(payload, list) else None
