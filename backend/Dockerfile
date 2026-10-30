# One image for api, worker, migrate and mcp-operations. Build context: repository root.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/srv/.venv

RUN pip install --no-cache-dir uv==0.6.16

WORKDIR /srv
# Dependencies first (cached layer), then sources.
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY mcp_servers/operations/pyproject.toml mcp_servers/operations/pyproject.toml
RUN uv sync --frozen --no-dev --all-packages --no-install-workspace

COPY backend backend
COPY mcp_servers mcp_servers
RUN uv sync --frozen --no-dev --all-packages

ENV PATH=/srv/.venv/bin:$PATH \
    PYTHONPATH=/srv/backend:/srv/mcp_servers/operations

RUN useradd --system --uid 10001 app
USER app
WORKDIR /srv/backend
EXPOSE 8000 3001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
