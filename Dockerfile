FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

# Install build deps with apt cache
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# pip wheel cache persisted across builds via BuildKit cache mount
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_TRUSTED_HOST=mirrors.aliyun.com
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --user -r requirements.txt

FROM python:3.12-slim-bookworm

WORKDIR /app

# Runtime deps only (no gcc) — use apt cache
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

COPY src/ src/
COPY config/ config/
COPY scripts/ scripts/
COPY .env.example .env.example

# 验证 Socket.IO 事件名一致性
RUN python scripts/validate-events.py

ENV PYTHONPATH=/app/src
ENV ANIMETTA_HOST=0.0.0.0
ENV ANIMETTA_PORT=12394
ENV ANIMETTA_LOG_LEVEL=INFO

EXPOSE 12394

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:12394/health')" || exit 1

CMD ["python", "-m", "animetta.core.socketio_server"]
