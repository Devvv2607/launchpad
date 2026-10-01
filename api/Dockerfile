# Build context: repository root (see docker-compose.yml).
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/api

# Install dependencies first for layer caching.
COPY api/pyproject.toml ./
RUN mkdir -p src/launchpad && touch src/launchpad/__init__.py && pip install . && pip uninstall -y launchpad

COPY api/ ./
RUN pip install --no-deps . \
    && useradd --system --uid 10001 launchpad
USER launchpad

EXPOSE 8000
CMD ["uvicorn", "launchpad.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
