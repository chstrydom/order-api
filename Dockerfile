# Image used by both the `api` and `worker` services (see docker-compose.yml).
ARG PYTHON_VERSION=3.14
# Pin to the uv version you use locally (`uv --version`) for reproducible builds.
ARG UV_VERSION=latest

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim

COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install dependencies first so this layer is cached until the lockfile changes.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

RUN useradd --system --no-create-home appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "order_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
