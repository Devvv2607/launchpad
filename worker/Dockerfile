# Build context: repository root (see docker-compose.yml).
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# The worker shares models, config and services with the API package.
COPY api/ ./api/
RUN pip install ./api
COPY worker/ ./worker/
RUN pip install --no-deps ./worker \
    && useradd --system --uid 10001 launchpad
USER launchpad
WORKDIR /app/api

CMD ["arq", "launchpad_worker.main.WorkerSettings"]
