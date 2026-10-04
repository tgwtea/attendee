FROM ghcr.io/astral-sh/uv:0.12.5 AS uv
FROM python:3.13-slim-bookworm AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 attendee \
    && useradd --uid 10001 --gid attendee --no-create-home attendee \
    && mkdir -p /app/data \
    && chown attendee:attendee /app/data
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY --chmod=755 scripts/entrypoint.sh ./entrypoint.sh
USER attendee:attendee
ENTRYPOINT ["/app/entrypoint.sh"]
