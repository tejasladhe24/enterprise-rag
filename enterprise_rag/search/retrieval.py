from sqlalchemy import func, select
from sqlalchemy.orm import Session

from enterprise_rag.lib.db import Chunk as DbChunk
from enterprise_rag.lib.db import engine


def _fetch_chunks(stmt) -> list[DbChunk]:
    with Session(engine) as session:
        return list(session.scalars(stmt).all())


def search_vector(query_embedding: list[float], limit: int) -> list[DbChunk]:
    if not query_embedding:
        return []

    distance = DbChunk.embedding.cosine_distance(query_embedding)
    stmt = (
        select(DbChunk)
        .where(DbChunk.embedding.isnot(None))
        .order_by(distance)
        .limit(limit)
    )
    return _fetch_chunks(stmt)


def search_keyword(query: str, limit: int) -> list[DbChunk]:
    ts_query = func.plainto_tsquery("english", query)
    ts_vector = func.to_tsvector("english", DbChunk.text)
    rank = func.ts_rank_cd(ts_vector, ts_query)
    stmt = (
        select(DbChunk)
        .where(ts_vector.op("@@")(ts_query))
        .order_by(rank.desc())
        .limit(limit)
    )
    return _fetch_chunks(stmt)


def merge_chunks_by_id(*chunk_lists: list[DbChunk]) -> list[DbChunk]:
    merged: dict[int, DbChunk] = {}
    for chunks in chunk_lists:
        for chunk in chunks:
            merged[chunk.id] = chunk
    return list(merged.values())
