FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (layer caching). The tracing extra is required in
# the production image so Azure Monitor/App Insights export can be enabled via
# environment variables without rebuilding the container.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra tracing --no-install-project

# Copy application code
COPY agent.py agent_deepagents.py appdb.py library.py server.py tracing.py trace_logging.py upload_policy.py ./
COPY skills/ ./skills/
COPY seed_docs/ ./seed_docs/

# Create workspace directory
RUN mkdir -p /workspace

ENV WORKSPACE=/workspace
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
