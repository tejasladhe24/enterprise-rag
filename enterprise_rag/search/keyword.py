from sqlalchemy import func, select
from sqlalchemy.orm import Session

from enterprise_rag.lib.db import Chunk as DbChunk
from enterprise_rag.lib.db import engine


def search_chunks_by_fts(query: str, k: int = 10) -> list[DbChunk]:
    ts_query = func.plainto_tsquery("english", query)
    ts_vector = func.to_tsvector("english", DbChunk.text)
    rank = func.ts_rank_cd(ts_vector, ts_query)

    stmt = (
        select(DbChunk)
        .where(ts_vector.op("@@")(ts_query))
        .order_by(rank.desc())
        .limit(k)
    )

    with Session(engine) as session:
        return list(session.scalars(stmt).all())
