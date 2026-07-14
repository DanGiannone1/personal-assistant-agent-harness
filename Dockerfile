FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY *.py ./
COPY workbench_core/ ./workbench_core/
# app.py imports appdb/library from session-container/ (added to sys.path at startup).
# seed_docs/ must ride along: appdb seeds the owner doc's library from it, and the
# orchestrator can be the first seeder (POST /sessions) — without it the library seeds empty.
COPY session-container/appdb.py session-container/library.py ./session-container/
COPY session-container/seed_docs/ ./session-container/seed_docs/

ENV PATH="/app/.venv/bin:$PATH"

RUN adduser --disabled-password --gecos "" --uid 1000 appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
