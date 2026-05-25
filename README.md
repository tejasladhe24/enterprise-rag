# Enterprise RAG

`enterprise_rag` is a project designed to enable large-scale document ingestion, chunking, and retrieval-augmented generation (RAG) workflows using modern cloud and orchestration technologies.

## Key Features

- **Multipart Document Uploads:** Supports uploading large files via a web frontend with S3-compatible backend storage. Documents up to a configurable maximum file size can be uploaded and stored efficiently.
- **File Type Support:** Handles various document formats, including PDF, DOCX, DOC, TXT, and Markdown files.
- **Automated Chunking:** Each document is split ("chunked") into logically coherent segments using the `DoclingChunker`, optimizing them for downstream retrieval and machine learning use cases.
- **Database Integration:** Both documents and their respective chunks are stored in a relational database for efficient indexing and querying.
- **Celery Task Queue:** Heavy data ingestion and document processing are orchestrated asynchronously using Celery workers to maximize scalability.
- **FastAPI Backend:** RESTful endpoints (using FastAPI) for upload coordination, task dispatch, and retrieval, with CORS enabled for easy web integrations.
- **S3 Storage Integration:** Persistent document storage is provided via any S3-compatible object storage (e.g., AWS S3, MinIO).

## Typical Workflow

1. **Upload:** Users upload files through a web UI or directly via API.
2. **Process:** The system validates the file (type/size), computes a SHA256 digest, and asynchronously dispatches a Celery task to ingest the document.
3. **Chunk:** The document is converted and chunked into pieces, each with accompanying metadata.
4. **Store:** All chunks and the original document metadata are stored in both S3 and the relational database.
5. **Retrieve:** Downstream retrieval-augmented generation pipelines can then fetch, rank, and utilize these chunks for search, QA, or generative AI applications.

## Technologies Used

- **FastAPI** for REST API endpoints
- **Celery** for asynchronous task processing
- **SQLAlchemy** for ORM and DB interaction
- **S3 (boto3)** for object storage
- **Pydantic** for schema validation
- **Modern JavaScript Web Frontend** for uploads

## Use Cases

- Enterprise knowledge ingestion and search
- Document QA systems
- Data preparation for RAG-based LLMs

## Getting Started

1. **Deploy storage and database** (S3-compatible bucket, SQL database)
2. **Run backend FastAPI server**
3. **Start Celery worker(s)**
4. **Use the provided web frontend or API to upload and ingest documents**

For more detailed information, see the source code and documentation for each component in the repository.
