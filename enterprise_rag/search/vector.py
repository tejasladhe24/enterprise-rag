from sqlalchemy import select
from sqlalchemy.orm import Session

from enterprise_rag.lib.db import Chunk as DbChunk
from enterprise_rag.lib.db import engine


def search_chunks_by_pgvector(query_embedding: list[float], k: int = 10) -> list[DbChunk]:
    if not query_embedding:
        return []

    distance = DbChunk.embedding.cosine_distance(query_embedding)

    stmt = (
        select(DbChunk)
        .where(DbChunk.embedding.isnot(None))
        .order_by(distance)
        .limit(k)
    )

    with Session(engine) as session:
        return list(session.scalars(stmt).all())
