#!/bin/sh
# Container entrypoint: optional migrations, then uvicorn.
set -eu

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "Applying database migrations..."
    alembic upgrade head
fi

# One worker by default: embedded Chroma (CHROMA_MODE=persistent) is single-process, and
# document ingestion runs as in-process background tasks. Scale out with CHROMA_MODE=http.
exec uvicorn app.main:create_app --factory \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-1}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
    --timeout-graceful-shutdown 30
