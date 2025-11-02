# Multi-stage build for production optimization
FROM python:3.12-slim as base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libssl-dev \
        libffi-dev \
        curl \
        && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements first for better caching
COPY pyproject.toml uv.lock* ./
COPY backend/pyproject.toml backend/uv.lock* ./backend/

# Install UV and dependencies
RUN pip install uv
RUN uv pip install --system --frozen-lockfile

# Copy application code
COPY backend/ ./backend/

# Production stage
FROM python:3.12-slim as production

# Install runtime dependencies only
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libssl1.1 \
        && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Set work directory
WORKDIR /app

# Install UV
RUN pip install uv

# Copy installed packages from base
COPY --from=base /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=base /usr/local/bin/uv /usr/local/bin/uv

# Copy application code
COPY --chown=appuser:appuser backend/ ./backend/

# Set ownership and permissions
RUN chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run application
CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]