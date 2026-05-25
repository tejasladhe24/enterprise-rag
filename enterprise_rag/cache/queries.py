import json

from redis import Redis

from enterprise_rag.lib.db import Chunk as DbChunk
from enterprise_rag.utils.settings import settings

redis_client = Redis.from_url(f"{settings.REDIS_URL}/2")


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
    expires_in: int = 60 * 60 * 12,
) -> None:
    if not chunks:
        return

    redis_client.set(
        query,
        json.dumps([_chunk_to_dict(chunk) for chunk in chunks]),
        ex=expires_in,
    )


def get_cached_query_results(query: str) -> list[DbChunk] | None:
    results = redis_client.get(query)
    if not results:
        return None
    return [_dict_to_chunk(item) for item in json.loads(results)]
