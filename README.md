# Enterprise RAG

Document ingestion, chunking, and hybrid search for retrieval-augmented generation (RAG) workflows. Upload documents through a web UI or API, process them asynchronously, store chunks with embeddings in PostgreSQL, and search with vector + full-text retrieval.

## Architecture

```mermaid
flowchart TB
    subgraph clients["Clients"]
        FE["Frontend :3000"]
    end

    subgraph api["API layer"]
        API["FastAPI :8000"]
    end

    subgraph storage["Storage"]
        MINIO["MinIO S3 :9000"]
        PG[("PostgreSQL + pgvector + FTS")]
        REDIS[("Redis")]
    end

    subgraph workers["Workers"]
        CELERY["Celery worker"]
    end

    subgraph external["External"]
        EMBED["OpenAI-compatible embeddings API"]
    end

    FE -->|"upload zip / multipart"| API
    FE -->|"POST /api/search"| API
    API -->|"presigned URLs / put_object"| MINIO
    MINIO -->|"ObjectCreated notification"| API
    API -->|"ingest_doc_task"| REDIS
    REDIS --> CELERY
    CELERY -->|"chunk + embed + store"| PG
    CELERY --> EMBED
    API -->|"search read/write cache"| REDIS
    API -->|"vector + FTS queries"| PG
    API --> EMBED
```

```mermaid
flowchart LR
    subgraph compose["Docker Compose services"]
        direction TB
        F[frontend]
        E[enterprise_rag]
        W[celery_worker]
        P[postgres]
        R[redis]
        M[minio]
    end

    F --> E
    E --> P
    E --> R
    E --> M
    W --> P
    W --> R
    W --> M
    E -.->|listens| M
```

| Service | Role |
|---------|------|
| **frontend** | Bun + React UI for zip/multipart uploads and search |
| **enterprise_rag** | FastAPI API, S3 upload listener, hybrid search |
| **celery_worker** | Async document ingest (chunking, embeddings) |
| **postgres** | Documents, chunks, pgvector HNSW + GIN full-text indexes |
| **redis** | Celery broker, query/embedding result cache |
| **minio** | S3-compatible object storage for uploaded files |

## Features

- **Uploads:** Zip upload and S3 multipart uploads (large files)
- **Supported formats:** PDF, DOCX, DOC, TXT, Markdown
- **Chunking:** Docling hybrid chunker with token metadata
- **Embeddings:** OpenAI-compatible API (`text-embedding-3-small` by default)
- **Hybrid search:** pgvector cosine similarity + PostgreSQL full-text search
- **Ranking:** Cross-encoder reranking (default) or reciprocal rank fusion (RRF)
- **Caching:** Redis caches normalized queries, embeddings, and search results
- **Observability:** Structlog JSON logs per search with step-level latency (ms)

## Quick start (Docker)

### Prerequisites

- Docker and Docker Compose
- OpenAI-compatible API key (e.g. Vercel AI Gateway, OpenAI)

### 1. Configure environment

Create a `.env` file in the project root:

```env
POSTGRES_USER=admin
POSTGRES_PASSWORD=your-postgres-password
POSTGRES_DB=enterprise_rag
REDIS_PASSWORD=your-redis-password
MINIO_ROOT_USER=admin
MINIO_ROOT_PASSWORD=your-minio-password

POSTGRES_URL=postgresql://admin:your-postgres-password@localhost:5432/enterprise_rag
REDIS_URL=redis://:your-redis-password@localhost:6379
LOG_FILE=logs/enterprise-rag.log
S3_ENDPOINT_URL=http://localhost:9000
S3_PUBLIC_ENDPOINT_URL=http://localhost:9000
AWS_REGION=us-east-1

OPENAI_BASE_URL=https://your-ai-gateway/v1
AI_GATEWAY_API_KEY=your-api-key

# Optional search tuning
SEARCH_ENABLE_RERANK=false
LOG_LEVEL=INFO
```

**Environment notes:**

- Compose passes `${SEARCH_ENABLE_RERANK}` into the API container (see `docker-compose.yaml`). Set it in `.env` before `docker compose up`.
- Pydantic coerces string env values to the correct types (`false` → `False`, `5` → `5`).
- Inside Docker, `POSTGRES_URL`, `REDIS_URL`, and `S3_ENDPOINT_URL` use service hostnames (`postgres`, `redis`, `minio`) from Compose overrides.

### 2. Start the stack

```bash
docker compose up --build
```

| URL | Service |
|-----|---------|
| http://localhost:3000 | Frontend |
| http://localhost:8000 | API (`/docs` for OpenAPI) |
| http://localhost:9001 | MinIO console |

### 3. Use the app

1. Open the frontend and upload documents (zip or individual files).
2. Wait for Celery to ingest and embed chunks (check `docker logs celery_worker`).
3. Search from the UI or call `POST /api/search`.
4. Inspect search latency: `docker logs enterprise_rag` or `logs/enterprise-rag.log` (event `search_pipeline_completed`).

## Document ingestion flow

```mermaid
sequenceDiagram
    actor User
    participant FE as Frontend
    participant API as FastAPI
    participant S3 as MinIO
    participant R as Redis
    participant CW as Celery worker
    participant PG as PostgreSQL
    participant LLM as Embeddings API

    User->>FE: Upload file(s)
    alt Zip upload
        FE->>API: POST /api/uploads/zip
        API->>S3: put_object per file
    else Multipart upload
        FE->>API: POST /api/uploads/multipart/urls
        API-->>FE: presigned part URLs
        FE->>S3: PUT parts directly
        FE->>API: POST /api/uploads/multipart/complete
        API->>S3: complete_multipart_upload
    end

    S3-->>API: ObjectCreated event
    API->>R: enqueue ingest_doc_task
    R->>CW: deliver task
    CW->>S3: read object bytes
    CW->>CW: Docling convert + chunk
    CW->>LLM: embed_texts (batch)
    LLM-->>CW: vectors
    CW->>PG: INSERT document + chunks
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/uploads/zip` | Upload a `.zip` of documents |
| `POST` | `/api/uploads/multipart/urls` | Start multipart upload (presigned part URLs) |
| `POST` | `/api/uploads/multipart/complete` | Complete multipart upload |
| `POST` | `/api/search` | Hybrid search over ingested chunks |

**Search request:**

```json
{ "query": "your question here" }
```

**Search response:** list of matching chunks with `id`, `document_id`, `text`, `chunk_index`, `token_count`, and optional `score`.

## Search pipeline

Relevant code: `enterprise_rag/search/pipeline.py`.

### Cached query (fast path)

```mermaid
flowchart LR
    Q[User query] --> N[normalize_query]
    N --> R{Redis results cache?}
    R -->|hit| OUT[Return chunks]
    R -->|miss| COLD[Cold pipeline]
```

### Cold query (full pipeline)

```mermaid
flowchart TB
    START([POST /api/search]) --> CACHE{Results in Redis?}
    CACHE -->|yes| RETURN([Return cached chunks])
    CACHE -->|no| PARALLEL

    subgraph PARALLEL["Parallel (thread pool)"]
        EMB[embed_text<br/>embedding cache]
        FTS[search_keyword<br/>PostgreSQL FTS]
    end

    PARALLEL --> VEC{Embedding available?}
    VEC -->|yes| VSEARCH[search_vector<br/>pgvector HNSW]
    VEC -->|no| EMPTY{Any keyword hits?}
    VSEARCH --> FUSE
    FTS --> FUSE
    EMPTY -->|no| NONE([Empty result])
    EMPTY -->|yes| FUSE

    subgraph FUSE["Fusion"]
        direction TB
        RERANK{SEARCH_ENABLE_RERANK?}
        RERANK -->|true| CE[cross-encoder rerank<br/>singleton model]
        RERANK -->|false| RRF[reciprocal rank fusion]
    end

    FUSE --> WRITE[cache_query_results]
    WRITE --> RETURN2([Return chunks])
```

```mermaid
sequenceDiagram
    participant API as FastAPI
    participant PL as search_pipeline
    participant RC as Redis cache
    participant POOL as Thread pool
    participant PG as PostgreSQL
    participant LLM as Embeddings API
    participant RER as Cross-encoder

    API->>PL: query
    PL->>RC: get_cached_query_results
    alt cache hit
        RC-->>PL: chunks
        PL-->>API: chunks
    else cache miss
        par Embedding + FTS
            PL->>POOL: embed_text
            POOL->>RC: embedding cache?
            POOL->>LLM: embeddings.create
            PL->>POOL: search_keyword
            POOL->>PG: FTS query
        end
        PL->>POOL: search_vector
        POOL->>PG: pgvector query
        alt rerank enabled
            PL->>RER: rank merged candidates
        else RRF only
            PL->>PL: reciprocal_rank_fusion
        end
        PL->>RC: cache_query_results
        PL-->>API: chunks
        PL->>PL: log search_pipeline_completed
    end
```

### Search observability

Every call to `search_pipeline` emits a structured log event **`search_pipeline_completed`** (structlog JSON to stdout and `LOG_FILE`).

| Field | Description |
|-------|-------------|
| `total_ms` | End-to-end pipeline latency |
| `cache_hit` | `true` if results came from Redis |
| `cache_lookup_ms` | Results cache read time |
| `embed_ms` | Query embedding (API + embedding cache) |
| `keyword_fts_ms` | Wait for full-text search (often ~0 if it finished during embed) |
| `parallel_retrieval_ms` | Wall time until embed and FTS both complete |
| `vector_ms` | pgvector search |
| `fusion_ms` | Cross-encoder rerank or RRF |
| `cache_write_ms` | Results cache write |
| `fusion_mode` | `"rerank"` or `"rrf"` (cold queries only) |
| `result_count` | Chunks returned |
| `vector_count` / `keyword_count` | Candidates before fusion |

Example:

```bash
docker logs enterprise_rag 2>&1 | grep search_pipeline_completed
```

Example log fields (cold query, rerank off):

```json
{
  "event": "search_pipeline_completed",
  "query": "machine learning basics",
  "cache_hit": false,
  "total_ms": 487.2,
  "cache_lookup_ms": 1.1,
  "embed_ms": 420.5,
  "keyword_fts_ms": 0.05,
  "parallel_retrieval_ms": 421.0,
  "vector_ms": 22.4,
  "fusion_ms": 0.8,
  "cache_write_ms": 1.9,
  "fusion_mode": "rrf",
  "result_count": 10
}
```

### Search tuning (environment variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `SEARCH_ENABLE_RERANK` | `true` | `false` uses RRF only (faster, no cross-encoder) |
| `SEARCH_VECTOR_K` | `5` | Vector retrieval top-K |
| `SEARCH_FTS_K` | `5` | Full-text retrieval top-K |
| `SEARCH_RESULT_K` | `10` | Final number of chunks returned |
| `SEARCH_CACHE_TTL_SECONDS` | `900` | Result cache TTL |
| `EMBEDDING_CACHE_TTL_SECONDS` | `3600` | Embedding cache TTL |
| `SEARCH_RRF_K` | `60` | RRF constant when rerank is off |
| `SEARCH_POOL_MAX_WORKERS` | `4` | Thread pool size for parallel search steps |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, …) |
| `DB_POOL_SIZE` | `10` | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | `20` | Extra connections under load |

For lowest latency on new queries, set `SEARCH_ENABLE_RERANK=false` and use the latency logs to confirm `fusion_ms` drops.

## Search latency benchmark (Glaive dataset)

Use `scripts/benchmark_search_latency.py` to measure end-to-end `POST /api/search` latency for questions in `glaive_rag_v1.json` and compute **p50, p90, p99** (plus min, max, mean).

The dataset has **51,354** questions. Start with a sample or limit — a full run can take many hours.

```bash
# Health check first
curl -s http://localhost:8000/api/health

# 100 sequential queries (with warmup)
python scripts/benchmark_search_latency.py --limit 100 --warmup

# 200 sequential queries
python scripts/benchmark_search_latency.py --limit 200 --warmup

# Random sample of 500
python scripts/benchmark_search_latency.py --sample 500 --warmup --shuffle

# Full dataset (prompts for confirmation)
python scripts/benchmark_search_latency.py --yes
```

**Output** (under `benchmark_results/`):

| File | Contents |
|------|----------|
| `search_benchmark_<timestamp>.json` | Full report + per-query latencies |
| `search_benchmark_<timestamp>.csv` | CSV for spreadsheets (`is_outlier` column) |
| `search_benchmark_<timestamp>_summary.txt` | Trimmed + raw percentile summary |

Console prints **trimmed** percentiles (outliers excluded) and **raw** percentiles for comparison. By default, the slowest ~2% of requests (above **p98**) are treated as outliers and omitted from primary p50/p90/p99. Use `--outlier-method iqr` or `--outlier-method none` to change behavior.

Compare with server-side step timings in `search_pipeline_completed` logs.

### Latest benchmark results

Run: `python scripts/benchmark_search_latency.py --limit 100 --warmup`  
Report: `benchmark_results/search_benchmark_20260525T173207Z.json`  
Config: `SEARCH_ENABLE_RERANK=false` (RRF only, no cross-encoder), sequential first 100 Glaive questions, API at `http://localhost:8000`.

| Metric | Value |
|--------|-------|
| Queries | 100 (all HTTP 200) |
| Duration | 80.5 s (~1.24 q/s) |
| Outliers excluded | 2 (tail p98, > 2023 ms) |

**Latency (ms) — trimmed** (primary; outliers excluded):

| | ms |
|--|-----|
| p50 | 672 |
| p90 | 1139 |
| p99 | 1633 |
| mean | 768 |
| min | 4 |
| max | 2019 |

**Latency (ms) — raw** (all 100 requests):

| | ms |
|--|-----|
| p50 | 674 |
| p90 | 1188 |
| p99 | 2214 |
| mean | 805 |
| max | 3099 |

**Outliers** (excluded from trimmed stats):

| Dataset idx | Latency | Note |
|-------------|---------|------|
| 27 | 2205 ms | Cold-path spike |
| 35 | 3099 ms | Cold-path spike |

The **~4 ms** minimum reflects Redis result cache hits on repeated or normalized queries during the run. Typical cold-path latency is roughly **650–1200 ms** (p50–p90) with reranking disabled.

For comparison with cross-encoder reranking enabled (`SEARCH_ENABLE_RERANK=true`), expect higher p90/p99 and occasional multi-second outliers on CPU.

```mermaid
flowchart LR
    JSON[glaive_rag_v1.json] --> SCRIPT[benchmark_search_latency.py]
    SCRIPT --> API[POST /api/search]
    API --> STATS[p50 p90 p99]
    STATS --> OUT[JSON + CSV + summary.txt]
```

## Project structure

```text
enterprise_rag/
├── main.py              # FastAPI app, upload + search routes
├── celery_app.py        # Celery configuration
├── cache/queries.py     # Redis cache for queries and embeddings
├── lib/                 # DB, embeddings, S3, chunking
├── search/
│   ├── pipeline.py      # Search orchestration + latency logging
│   ├── retrieval.py     # Vector + FTS queries
│   ├── fusion.py        # Reciprocal rank fusion
│   ├── reranking.py     # Singleton cross-encoder
│   └── executor.py      # Shared thread pool
├── repository/          # Document ingest persistence
├── tasks/               # Celery ingest task
└── utils/               # Settings, schemas, structlog logger

frontend/                # Bun + React upload/search UI
scripts/                 # benchmark_search_latency.py
docker-compose.yaml      # Full stack definition
Dockerfile               # API + worker image (CPU PyTorch)
```

## Local development (without Docker)

**Backend** (Python 3.11+):

```bash
pip install -e .
# Start Postgres, Redis, and MinIO locally; set .env accordingly
uvicorn enterprise_rag.main:app --reload --port 8000
celery -A enterprise_rag.celery_app:celery_app worker --loglevel=info
```

**Frontend:** see [frontend/README.md](frontend/README.md).

## Technologies

- FastAPI, Celery, SQLAlchemy, pgvector
- Redis, MinIO (S3-compatible), boto3
- Docling, OpenAI embeddings, rerankers (cross-encoder)
- Structlog (JSON logs with per-step search timings)
- Bun, React, Tailwind (frontend)

## GPU note

Reranking runs on **CPU** in the default Docker image (CPU-only PyTorch). NVIDIA GPU passthrough is not configured in Compose. Set `SEARCH_ENABLE_RERANK=false` for faster cold queries without a GPU.
