#!/bin/bash
set -e

# ---------------------------------------------------------------------------
# Animetta Docker Entrypoint
# Validates environment, detects optional services, starts nginx + Python backend
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Phase 0: Environment validation — fail fast on missing critical vars
# ---------------------------------------------------------------------------
validate_env() {
    local missing=()
    local required_vars=()

    if [ "${ANIMETTA_LLM:-}" = "deepseek" ]; then
        required_vars+=("DEEPSEEK_API_KEY")
    fi

    for var in "${required_vars[@]}"; do
        if [ -z "${!var:-}" ]; then
            missing+=("$var")
        fi
    done

    if [ ${#missing[@]} -gt 0 ]; then
        echo ""
        echo "=============================================="
        echo " [FATAL] Missing required environment variables"
        echo "=============================================="
        for var in "${missing[@]}"; do
            echo "   - $var"
        done
        echo ""
        echo " Set them in .env or docker-compose environment section."
        echo " Example .env entry:"
        for var in "${missing[@]}"; do
            echo "   $var=your_value_here"
        done
        echo "=============================================="
        exit 1
    fi

    echo "[entrypoint] Environment validation: OK"
}

run_static_preflight() {
    if [ "${ANIMETTA_CONFIG:-}" != "/app/config/config.golden.yaml" ]; then
        echo "[entrypoint] Golden static preflight: skipped (non-golden profile)"
        return 0
    fi

    echo "[entrypoint] Running golden static preflight..."
    python scripts/baseline_golden_path.py \
        --config "$ANIMETTA_CONFIG" \
        --project-root /app \
        --output-dir /app/data/baseline \
        --static-only
    echo "[entrypoint] Golden static preflight: OK"
}

# ---------------------------------------------------------------------------
# Phase 1: Optional service detection
# ---------------------------------------------------------------------------
detect_optional_services() {
    # Minecraft bridge requires Node.js
    if command -v node >/dev/null 2>&1; then
        HAS_NODE=1
        NODE_VERSION=$(node --version 2>/dev/null || echo "unknown")
    else
        HAS_NODE=0
    fi

    # MCP servers — check for common binaries
    HAS_MCP_FILESYSTEM=0
    if [ -x "/usr/local/bin/mcp-server-filesystem" ] || command -v mcp-server-filesystem >/dev/null 2>&1; then
        HAS_MCP_FILESYSTEM=1
    fi
}

print_optional_summary() {
    echo "[entrypoint] Optional services:"
    if [ "$HAS_NODE" -eq 1 ]; then
        echo "[entrypoint]   minecraft=available (Node.js $NODE_VERSION)"
    else
        echo "[entrypoint]   minecraft=skipped (Node.js not found)"
    fi

    if [ "$HAS_MCP_FILESYSTEM" -eq 1 ]; then
        echo "[entrypoint]   mcp_filesystem=available"
    else
        echo "[entrypoint]   mcp_filesystem=skipped (binary not found)"
    fi
}

# ---------------------------------------------------------------------------
# Phase 2: Runtime setup
# ---------------------------------------------------------------------------

# Create required directories if missing
mkdir -p /app/memory_db /app/data /app/logs
mkdir -p /var/log/nginx /var/lib/nginx /tmp

# Trap SIGTERM for graceful shutdown
cleanup() {
    echo "[entrypoint] Shutting down gracefully..."
    # Stop nginx
    nginx -s quit 2>/dev/null || true
    # Stop backend (forward SIGTERM)
    if [ -n "$BACKEND_PID" ]; then
        kill -TERM "$BACKEND_PID" 2>/dev/null || true
        wait "$BACKEND_PID" 2>/dev/null || true
    fi
    echo "[entrypoint] Shutdown complete."
    exit 0
}
trap cleanup SIGTERM SIGINT

# --- Run phases ---
validate_env
detect_optional_services
run_static_preflight

# Start nginx in background
echo "[entrypoint] Starting nginx..."
nginx -t && nginx

# Print optional service summary
print_optional_summary

# Start Python backend in foreground
echo "[entrypoint] Starting Animetta backend on port ${ANIMETTA_PORT:-12394}..."
python -m animetta.core.socketio_server &
BACKEND_PID=$!

# Wait for backend process
wait "$BACKEND_PID"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "[entrypoint] Backend exited with code $EXIT_CODE"
fi

# Cleanup nginx on exit
nginx -s quit 2>/dev/null || true

exit $EXIT_CODE
