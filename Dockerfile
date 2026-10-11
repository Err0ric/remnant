# syntax=docker/dockerfile:1
# Base images are pinned by tag for now; pin by digest before v0.1.0 (CLAUDE.md security rule 11).

FROM node:22-alpine AS web
WORKDIR /web
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM ghcr.io/astral-sh/uv:0.8-python3.12-bookworm-slim AS api
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm AS runtime
RUN useradd --system --uid 10001 --home /srv app \
    && mkdir -p /srv/data /srv/config \
    && chown -R app /srv/data
COPY --from=api /srv/backend /srv/backend
COPY --from=web /web/dist /srv/web
COPY templates/starter /srv/templates/starter
# Unbuffered: the one-time setup link and certificate fingerprint must reach `docker logs`
# at once, not sit in a pipe buffer.
ENV PYTHONUNBUFFERED=1 \
    PATH="/srv/backend/.venv/bin:$PATH" \
    APP__SERVER__STATIC_DIR=/srv/web \
    APP__PATHS__STARTER_TEMPLATES=/srv/templates/starter \
    APP__PATHS__DATA_DIR=/srv/data
WORKDIR /srv
USER app
EXPOSE 8080
CMD ["app-server"]
