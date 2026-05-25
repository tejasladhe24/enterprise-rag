from typing import Any, List, Optional

from pydantic import BaseModel


class ChunkMetadata(BaseModel):
    page_numbers: List[int] = []
    chunk_index: int
    token_count: Optional[int] = None
    source: Optional[str] = None


class Chunk(BaseModel):
    text: str
    metadata: ChunkMetadata


class ChunkResponse(BaseModel):
    chunks: List[Chunk]


class SearchChunkResult(BaseModel):
    id: int
    document_id: int
    text: str
    chunk_index: int
    token_count: int
    metadata: dict[str, Any] | None = None
    score: float | None = None
