from celery import Task

from enterprise_rag.lib.broker import celery_app
from enterprise_rag.lib.chunker import DoclingChunker
from enterprise_rag.repository.doc import ingest_doc
from enterprise_rag.utils.logger import logger

celery_app.conf.update(
    task_time_limit=3600,
    task_soft_time_limit=300,
)

chunker = DoclingChunker()


@celery_app.task(
    bind=True,
    name="enterprise_rag.tasks.ingest_doc_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def ingest_doc_task(self: Task, *, filename: str, file_bytes: bytes):
    logger.info(
        "ingest_doc_task_started",
        filename=filename,
        size_bytes=len(file_bytes),
    )
    result = ingest_doc(
        filename=filename,
        file_bytes=file_bytes,
        chunker=chunker,
        task_id=self.request.id,
    )
    return result.model_dump()
