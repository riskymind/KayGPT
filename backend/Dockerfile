# syntax=docker/dockerfile:1.7
# KayGPT backend (FastAPI). Build context: backend/

FROM ghcr.io/astral-sh/uv:0.12.17 AS uv

FROM python:3.12-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra s3 --no-install-project

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    APP_ENV=production \
    PORT=8000 \
    CHROMA_PERSIST_DIRECTORY=/data/chroma \
    UPLOAD_DIR=/data/uploads
RUN groupadd --system --gid 1001 kaygpt \
    && useradd --system --uid 1001 --gid kaygpt --home /app kaygpt \
    && mkdir -p /data/chroma /data/uploads \
    && chown -R kaygpt:kaygpt /data
WORKDIR /app
COPY --from=builder --chown=kaygpt:kaygpt /app/.venv /app/.venv
COPY --chown=kaygpt:kaygpt alembic.ini ./
COPY --chown=kaygpt:kaygpt alembic ./alembic
COPY --chown=kaygpt:kaygpt app ./app
COPY --chown=kaygpt:kaygpt scripts ./scripts
COPY --chown=kaygpt:kaygpt docker/entrypoint.sh /entrypoint.sh
USER kaygpt
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/v1/health', timeout=4)"
ENTRYPOINT ["/entrypoint.sh"]
