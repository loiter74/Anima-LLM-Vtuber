# ============================================================================
# Animetta — Core Dockerfile (Lightweight)
# ============================================================================
# Minimal image for remote/mock provider deployments.
# No CUDA, no local AI inference packages.
#
# Build and run the personal edition:
#   py -3.13 scripts/runtime_lifecycle.py anima-up
#
# GPU inference runs in the host-local Qwen runtime on port 8767.
# ============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Frontend builder
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS frontend-builder

RUN corepack enable \
    && corepack prepare pnpm@11.7.0 --activate \
    && pnpm config set registry https://registry.npmmirror.com

WORKDIR /build/frontend

# Docker only needs the Vite web bundle; the Electron desktop binary is not
# used in the nginx runtime image and is large/flaky to fetch during builds.
ENV ELECTRON_SKIP_BINARY_DOWNLOAD=1
ENV npm_config_electron_skip_binary_download=true

COPY frontend/.npmrc frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./

RUN pnpm install --frozen-lockfile

COPY frontend/ .

# Copy config needed by socket-events.ts import
COPY config/socket-events.json /build/config/socket-events.json

# Skip TypeScript check in Docker build (run vite build directly)
RUN pnpm exec vite build

# ---------------------------------------------------------------------------
# Stage 2: Python dependency builder
# ---------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS python-builder

WORKDIR /build

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Use Chinese pip mirror for faster downloads
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_TRUSTED_HOST=mirrors.aliyun.com

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --user -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 3: Runtime
# ---------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS runtime

ARG ANIMETTA_BUILD_FINGERPRINT=untracked
LABEL org.animetta.build-fingerprint="${ANIMETTA_BUILD_FINGERPRINT}"

WORKDIR /app

# Install runtime system deps
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get install -y --no-install-recommends ffmpeg nginx curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=python-builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy backend source
COPY src/animetta/ src/animetta/
COPY config/ config/
COPY scripts/ scripts/
COPY .env.example .env.example

# Validate Socket.IO event name consistency
RUN python scripts/validate-events.py

# Copy frontend build
COPY --from=frontend-builder /build/frontend/dist /app/frontend/dist

# Copy Docker config files
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Environment variables
ENV PYTHONPATH=/app/src
ENV ANIMETTA_HOST=0.0.0.0
ENV ANIMETTA_PORT=12394
ENV ANIMETTA_PROFILE=test

# Expose nginx (80) and backend (12394)
EXPOSE 80 12394

# Health check via nginx
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:80/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
