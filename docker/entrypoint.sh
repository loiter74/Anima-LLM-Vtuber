#!/bin/bash
set -euo pipefail

mkdir -p /app/memory_db /app/data /app/logs
mkdir -p /var/log/nginx /var/lib/nginx /tmp

cleanup() {
    echo "[entrypoint] Shutting down gracefully..."
    nginx -s quit 2>/dev/null || true
    if [ -n "${BACKEND_PID:-}" ]; then
        kill -TERM "$BACKEND_PID" 2>/dev/null || true
        wait "$BACKEND_PID" 2>/dev/null || true
    fi
}
trap cleanup SIGTERM SIGINT

echo "[entrypoint] Validating config/animetta.yaml for profile ${ANIMETTA_PROFILE:-<missing>}..."
python -c "from animetta.config.manifest import load_effective_config; c=load_effective_config(); print('[entrypoint] Config ready:', c.profile, c.version, c.semantic_hash)"

echo "[entrypoint] Starting nginx..."
nginx -t
nginx

echo "[entrypoint] Starting Animetta backend on port ${ANIMETTA_PORT:-12394}..."
python -m animetta.core.socketio_server &
BACKEND_PID=$!
wait "$BACKEND_PID"
