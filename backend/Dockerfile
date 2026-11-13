# syntax=docker/dockerfile:1

# ---- builder: resolve and install locked dependencies into a virtualenv -------------
FROM python:3.13-slim-bookworm AS builder

# uv is copied from its official image rather than installed with pip.
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Copy only the dependency manifests first so this layer is cached until they change.
# --frozen fails the build if uv.lock is out of date with pyproject.toml.
COPY pyproject.toml uv.lock ./

# Local embeddings (SentenceTransformers + CPU-only PyTorch) add roughly a gigabyte to the
# image. Build with `--build-arg INSTALL_LOCAL_EMBEDDINGS=false` when using
# EMBEDDING_PROVIDER=openai and the model code is not needed.
ARG INSTALL_LOCAL_EMBEDDINGS=true
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_LOCAL_EMBEDDINGS" = "true" ]; then extra="--extra local-embeddings"; else extra=""; fi; \
    uv sync --frozen --no-dev --no-install-project $extra

# ---- runtime: no build tools, no uv, non-root ----------------------------------------
FROM python:3.13-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/data/models

# Fixed UID/GID so file ownership on mounted volumes is predictable. /data/models holds
# the downloaded embedding model; it is a volume so the download happens once, not on
# every container start.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /data/uploads /data/models \
    && chown -R app:app /data

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app app ./app
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic

USER app
EXPOSE 8000

# `--proxy-headers` makes client IPs (needed for rate limiting in Phase 10) come from
# X-Forwarded-For when the app runs behind a reverse proxy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
