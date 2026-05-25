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

    POSTGRES_URL: str = Field(..., description="The URL of the PostgreSQL server")
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
