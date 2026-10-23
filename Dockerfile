FROM ghcr.io/astral-sh/uv:0.9.30-python3.12-bookworm-slim

# Tesseract with the Ukrainian model is needed for scanned PDFs (20 of them in the archive)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-ukr \
    && rm -rf /var/lib/apt/lists/*

# Limited uv concurrency: with the defaults Docker Desktop's BuildKit drops the connection
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CONCURRENT_DOWNLOADS=4 \
    UV_CONCURRENT_INSTALLS=2 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/opt/models

WORKDIR /app

# Dependencies first, so code changes don't reinstall them
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --group dev

COPY src ./src
RUN uv sync --frozen --group dev

# Bake the embedding model into the image: the bot starts without downloading anything
RUN python -m forest_bot.embeddings

COPY migrations ./migrations
COPY archive ./archive
COPY tests ./tests
COPY scripts ./scripts

CMD ["python", "-m", "forest_bot"]
