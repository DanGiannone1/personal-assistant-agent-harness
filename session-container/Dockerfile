FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (layer caching). The tracing extra is required in
# the production image so Azure Monitor/App Insights export can be enabled via
# environment variables without rebuilding the container.
COPY session-container/pyproject.toml session-container/uv.lock ./
RUN uv sync --frozen --no-dev --extra tracing --no-install-project

# Copy application code
COPY session-container/agent.py session-container/agent_deepagents.py session-container/appdb.py session-container/mvp_tool_schemas.py session-container/navsvc.py session-container/server.py session-container/skill_runtime.py session-container/tracing.py session-container/workload_auth.py ./
COPY session-container/product-skills/ ./product-skills/
COPY session-container/seed_docs/ ./seed_docs/
COPY workbench_core/ ./workbench_core/

# The runtime has no reason to run as root.  Keep the application and its
# ephemeral workspace writable by one fixed, non-privileged UID.
RUN addgroup --system --gid 10001 app && \
    adduser --system --uid 10001 --ingroup app --home /app app && \
    mkdir -p /workspace && chown -R 10001:10001 /app /workspace

ENV WORKSPACE=/workspace
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

USER 10001:10001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
