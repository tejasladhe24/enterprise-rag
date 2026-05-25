from pathlib import Path
from uuid import uuid4
from sqlalchemy.orm import Session
from enterprise_rag.lib.chunker import DoclingChunker
from enterprise_rag.lib.db import Chunk, Document, engine
from enterprise_rag.utils import sha256_digest
from enterprise_rag.utils.schemas import ChunkResponse
from enterprise_rag.utils.settings import settings
from enterprise_rag.utils.logger import logger

SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".doc", ".txt", ".md"]
max_file_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024


def is_supported_extension(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in SUPPORTED_EXTENSIONS


def ingest_doc(
    filename: str,
    file_bytes: bytes,
    chunker: DoclingChunker,
    task_id: str,
) -> ChunkResponse:
    if not is_supported_extension(filename):
        raise ValueError(f"Unsupported file extension: {filename}")

    if len(file_bytes) > max_file_size:
        raise ValueError(
            f"File size exceeds the maximum allowed size of {max_file_size} bytes"
        )

    content_sha256 = sha256_digest(file_bytes)

    logger.info(
        "document_received",
        task_id=task_id,
        content_sha256=content_sha256,
        filename=filename,
        size_bytes=len(file_bytes),
    )

    doc = chunker.converter.convert_bytes(file_bytes=file_bytes, filename=filename)
    chunk_response = chunker.chunk(dl_doc=doc)

    logger.info(
        "chunking_completed",
        task_id=task_id,
        content_sha256=content_sha256,
        chunk_count=len(chunk_response.chunks),
    )

    document_key = str(uuid4())
    with Session(engine) as session:
        document = Document(
            title=filename,
            content=doc.export_to_markdown()[:200],
            s3_key=f"documents/{document_key}/{filename}",
            hash=content_sha256,
        )
        session.add(document)
        session.flush()

        for chunk in chunk_response.chunks:
            session.add(
                Chunk(
                    document_id=document.id,
                    text=chunk.text,
                    chunk_index=chunk.metadata.chunk_index,
                    token_count=chunk.metadata.token_count or 0,
                    chunk_metadata=chunk.metadata.model_dump(),
                )
            )

        session.commit()

    logger.info(
        "document_ingested",
        task_id=task_id,
        content_sha256=content_sha256,
        filename=filename,
        size_bytes=len(file_bytes),
        chunk_count=len(chunk_response.chunks),
    )

    return chunk_response


def delete_document_by_id(document_id: str) -> None:
    with Session(engine) as session:
        session.query(Document).filter(Document.id == document_id).delete()
        session.commit()
