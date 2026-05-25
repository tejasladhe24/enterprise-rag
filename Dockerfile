FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./

# Install matched CPU torch + torchvision before docling/transformers (avoids nms mismatch).
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

RUN python - <<'PY'
import subprocess
import tomllib

with open("pyproject.toml", "rb") as file:
    deps = tomllib.load(file)["project"]["dependencies"]

subprocess.run(["pip", "install", "--no-cache-dir", *deps], check=True)
PY

COPY enterprise_rag ./enterprise_rag
COPY index.html ./index.html

RUN mkdir -p logs .cache/huggingface

EXPOSE 8000

CMD ["uvicorn", "enterprise_rag.main:app", "--host", "0.0.0.0", "--port", "8000"]
