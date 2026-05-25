from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    APP_NAME: str = "docling_chunk_service"
    MAX_FILE_SIZE_MB: int = 100
    REDIS_URL: str = Field(..., description="The URL of the Redis server")

    LOG_LEVEL: str = "INFO"
    LOG_FILE: Path = Path("logs/enterprise-rag.log")
    LOG_FILE_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_FILE_BACKUP_COUNT: int = 5
    ENABLE_OCR: bool = True

    AI_GATEWAY_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536
    EMBEDDING_BATCH_SIZE: int = 64
    EMBEDDING_CACHE_TTL_SECONDS: int = 60 * 60

    SEARCH_VECTOR_K: int = 5
    SEARCH_FTS_K: int = 5
    SEARCH_RESULT_K: int = 10
    SEARCH_ENABLE_RERANK: bool = Field(
        default=True,
        description="Whether to enable cross-encoder reranking (false uses RRF only)",
    )
    SEARCH_RRF_K: int = 60
    SEARCH_CACHE_TTL_SECONDS: int = 60 * 15
    SEARCH_POOL_MAX_WORKERS: int = 4

    POSTGRES_URL: str = Field(..., description="The URL of the PostgreSQL server")
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_PRE_PING: bool = True
    S3_ENDPOINT_URL: str = Field(..., description="The URL of the S3 server")
    S3_PUBLIC_ENDPOINT_URL: str | None = Field(
        default=None,
        description=(
            "Browser-reachable S3 URL for presigned multipart uploads. "
            "Use when S3_ENDPOINT_URL is a Docker-internal hostname (e.g. http://localhost:9000)."
        ),
    )
    S3_BUCKET_NAME: str = Field(
        default="uploads", description="S3 bucket for document uploads"
    )
    AWS_REGION: str = Field(..., description="AWS region")
    MINIO_ROOT_USER: str = Field(..., description="The root user for the MinIO server")
    MINIO_ROOT_PASSWORD: str = Field(
        ..., description="The root password for the MinIO server"
    )


settings = Settings()
