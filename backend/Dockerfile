# Build context is ./backend in both Compose and CI.
FROM python:3.12-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN pip install uv==0.12.17

# Only dependency metadata enters the dependency layer. No .env, database,
# logs, tests, coverage output, or generated caches are in this allowlist.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim-bookworm AS production

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/backend"

WORKDIR /app/backend
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app appuser \
    && mkdir -p /app/backend/data \
    && chown -R appuser:appuser /app/backend/data

COPY --from=builder /app/.venv /app/.venv

# Explicit source allowlist. Wildcards are limited to *.py, so __pycache__,
# .env*, data/, logs/, backups/, coverage, and test artifacts cannot be copied.
COPY --chown=appuser:appuser app/*.py ./app/
COPY --chown=appuser:appuser app/api/*.py ./app/api/
COPY --chown=appuser:appuser app/db/*.py ./app/db/
COPY --chown=appuser:appuser app/models/*.py ./app/models/
COPY --chown=appuser:appuser app/services/*.py ./app/services/
COPY --chown=appuser:appuser app/utils/*.py ./app/utils/
COPY --chown=appuser:appuser main.py ./main.py
COPY --chown=appuser:appuser migrations/*.py ./migrations/

USER appuser
EXPOSE 8000

# Readiness combines the published HTTP liveness endpoint with SQLite
# quick_check. Python is already present, so no curl/wget runtime is required.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import os,sqlite3,urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3).close(); p=os.environ['DATABASE_URL'].rsplit('///',1)[1]; c=sqlite3.connect(p,timeout=3); ok=c.execute('PRAGMA quick_check').fetchone()[0]; c.close(); assert ok == 'ok', ok"]

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
