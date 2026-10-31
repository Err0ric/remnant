# syntax=docker/dockerfile:1
# Base images are pinned by digest (CLAUDE.md security rule 11). To update: run the
# release-checks workflow, take digests at least 14 days old from its "image" notices.

FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS web
WORKDIR /web
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM ghcr.io/astral-sh/uv:0.8-python3.12-bookworm-slim@sha256:1e63e300ec9908733d44d2eaa37688dd2c51fc7c1350f8fd046413d05f21486c AS api
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS runtime
RUN useradd --system --uid 10001 --home /srv app \
    && mkdir -p /srv/data /srv/config \
    && chown -R app /srv/data
COPY --from=api /srv/backend /srv/backend
COPY --from=web /web/dist /srv/web
COPY templates/starter /srv/templates/starter
COPY library /srv/library
# The commit shown on About ("0.3.0+1a2b3c4"); empty when the build was not given one.
ARG GIT_COMMIT=""
RUN printf '%s' "$GIT_COMMIT" > /srv/BUILD_COMMIT
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
