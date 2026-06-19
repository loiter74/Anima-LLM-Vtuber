#!/bin/bash
# Stop MC server
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Stopping Animetta MC Server..."
docker compose down

echo "Server stopped."
