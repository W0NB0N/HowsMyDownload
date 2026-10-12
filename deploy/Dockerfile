# Multi-stage / Multi-arch Production Dockerfile for Download Notifs Backend
FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install minimal system dependencies & curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install project dependencies (cached unless dependencies in server/pyproject.toml change)
COPY server/pyproject.toml ./server/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
      "fastapi>=0.115.0" \
      "uvicorn[standard]>=0.32.0" \
      "pydantic>=2.9.0" \
      "pydantic-settings>=2.5.0" \
      "firebase-admin>=6.5.0" \
      "google-cloud-firestore>=2.19.0" \
      "websockets>=13.1" \
      "cryptography>=43.0.0" \
      "httpx>=0.27.0"

# Copy application source code (changes to source code will NOT re-download dependencies)
COPY server/ ./server/

# Create non-root unprivileged service user
RUN useradd -m -u 10001 appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Launch production server with Uvicorn
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
