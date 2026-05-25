import io
import math
import mimetypes
import threading
import zipfile
from pathlib import Path
from uuid import uuid4

from botocore.exceptions import ClientError
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from enterprise_rag.lib.broker import celery_app
from enterprise_rag.lib.bucket import minio_client, s3, s3_presign
from enterprise_rag.lib.db import Chunk as DbChunk
from enterprise_rag.search import search_pipeline
from enterprise_rag.search.reranking import get_reranker
from enterprise_rag.utils.schemas import SearchChunkResult
from enterprise_rag.utils.settings import settings

PART_SIZE_BYTES = 5 * 1024 * 1024  # S3 minimum part size (except last part)

app = FastAPI(title=settings.APP_NAME)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ensure_bucket_exists() -> None:
    try:
        s3.head_bucket(Bucket=settings.S3_BUCKET_NAME)
    except ClientError:
        s3.create_bucket(Bucket=settings.S3_BUCKET_NAME)


def listen_for_document_upload_complete_event() -> None:
    with minio_client.listen_bucket_notification(
        settings.S3_BUCKET_NAME,
        events=["s3:ObjectCreated:*"],
    ) as event_stream:
        for event in event_stream:
            records = event.get("Records", [])
            for record in records:
                object_key = record["s3"]["object"]["key"]
                response = minio_client.get_object(
                    settings.S3_BUCKET_NAME,
                    object_key,
                )
                try:
                    file_bytes = response.read()
                finally:
                    response.close()
                    response.release_conn()

                celery_app.send_task(
                    "enterprise_rag.tasks.ingest_doc_task",
                    kwargs={
                        "filename": Path(object_key).name,
                        "file_bytes": file_bytes,
                    },
                )


@app.on_event("startup")
def on_startup() -> None:
    ensure_bucket_exists()
    if settings.SEARCH_ENABLE_RERANK:
        threading.Thread(
            target=get_reranker,
            name="reranker-warmup",
            daemon=True,
        ).start()
    threading.Thread(
        target=listen_for_document_upload_complete_event,
        name="s3-upload-listener",
        daemon=True,
    ).start()


class MultipartUploadUrlsRequest(BaseModel):
    filename: str
    file_size: int = Field(gt=0)
    content_type: str = "application/octet-stream"
    part_size: int = Field(default=PART_SIZE_BYTES, ge=5 * 1024 * 1024)


class PartUploadUrl(BaseModel):
    part_number: int
    url: str


class MultipartUploadUrlsResponse(BaseModel):
    upload_id: str
    key: str
    bucket: str
    part_size: int
    parts: list[PartUploadUrl]


class CompletedPart(BaseModel):
    part_number: int
    etag: str


class CompleteMultipartUploadRequest(BaseModel):
    upload_id: str
    key: str
    parts: list[CompletedPart]


class CompleteMultipartUploadResponse(BaseModel):
    key: str
    bucket: str
    location: str


class ZipUploadFileResult(BaseModel):
    filename: str
    key: str
    bucket: str
    size: int


class ZipUploadResponse(BaseModel):
    files: list[ZipUploadFileResult]
    skipped: list[str]


def _should_skip_zip_entry(entry_name: str) -> bool:
    path = Path(entry_name)
    if path.name.startswith("."):
        return True
    return any(part.startswith(".") or part == "__MACOSX" for part in path.parts)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/uploads/zip", response_model=ZipUploadResponse)
def upload_zip(file: UploadFile = File(...)) -> ZipUploadResponse:
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    max_file_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    uploaded: list[ZipUploadFileResult] = []
    skipped: list[str] = []

    try:
        with zipfile.ZipFile(io.BytesIO(file.file.read())) as archive:
            for info in archive.infolist():
                if info.is_dir() or _should_skip_zip_entry(info.filename):
                    continue

                filename = Path(info.filename).name
                if not filename:
                    skipped.append(info.filename)
                    continue

                file_bytes = archive.read(info.filename)
                if len(file_bytes) > max_file_size:
                    skipped.append(f"{info.filename} (exceeds max size)")
                    continue

                key = f"{uuid4()}/{filename}"
                content_type, _ = mimetypes.guess_type(filename)
                try:
                    s3.put_object(
                        Bucket=settings.S3_BUCKET_NAME,
                        Key=key,
                        Body=file_bytes,
                        ContentType=content_type or "application/octet-stream",
                    )
                except ClientError as exc:
                    raise HTTPException(status_code=502, detail=str(exc)) from exc

                uploaded.append(
                    ZipUploadFileResult(
                        filename=filename,
                        key=key,
                        bucket=settings.S3_BUCKET_NAME,
                        size=len(file_bytes),
                    )
                )
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Invalid zip file") from exc

    if not uploaded and not skipped:
        raise HTTPException(status_code=400, detail="Zip archive contains no files")

    return ZipUploadResponse(files=uploaded, skipped=skipped)


@app.post("/api/uploads/multipart/urls", response_model=MultipartUploadUrlsResponse)
def create_multipart_upload_urls(
    body: MultipartUploadUrlsRequest,
) -> MultipartUploadUrlsResponse:
    key = f"{uuid4()}/{body.filename}"
    part_count = math.ceil(body.file_size / body.part_size)

    try:
        multipart = s3.create_multipart_upload(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
            ContentType=body.content_type,
        )
        upload_id = multipart["UploadId"]

        parts: list[PartUploadUrl] = []
        for part_number in range(1, part_count + 1):
            url = s3_presign.generate_presigned_url(
                ClientMethod="upload_part",
                Params={
                    "Bucket": settings.S3_BUCKET_NAME,
                    "Key": key,
                    "UploadId": upload_id,
                    "PartNumber": part_number,
                },
                ExpiresIn=3600,
            )
            parts.append(PartUploadUrl(part_number=part_number, url=url))

        return MultipartUploadUrlsResponse(
            upload_id=upload_id,
            key=key,
            bucket=settings.S3_BUCKET_NAME,
            part_size=body.part_size,
            parts=parts,
        )
    except ClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/api/uploads/multipart/complete",
    response_model=CompleteMultipartUploadResponse,
)
def complete_multipart_upload(
    body: CompleteMultipartUploadRequest,
) -> CompleteMultipartUploadResponse:
    s3_parts = [
        {
            "PartNumber": part.part_number,
            "ETag": part.etag,
        }
        for part in sorted(body.parts, key=lambda p: p.part_number)
    ]

    try:
        result = s3.complete_multipart_upload(
            Bucket=settings.S3_BUCKET_NAME,
            Key=body.key,
            UploadId=body.upload_id,
            MultipartUpload={"Parts": s3_parts},
        )
        return CompleteMultipartUploadResponse(
            key=body.key,
            bucket=settings.S3_BUCKET_NAME,
            location=result.get("Location", ""),
        )
    except ClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class SearchRequest(BaseModel):
    query: str


class SearchResponse(BaseModel):
    chunks: list[SearchChunkResult]


def _to_search_result(chunk: DbChunk) -> SearchChunkResult:
    return SearchChunkResult(
        id=chunk.id,
        document_id=chunk.document_id,
        text=chunk.text,
        chunk_index=chunk.chunk_index,
        token_count=chunk.token_count,
        metadata=chunk.chunk_metadata,
        score=getattr(chunk, "score", None),
    )


@app.post("/api/search", response_model=SearchResponse)
def search(body: SearchRequest) -> SearchResponse:
    chunks = search_pipeline(body.query)
    return SearchResponse(chunks=[_to_search_result(chunk) for chunk in chunks])
