#!/bin/bash
# Start MC server for Animetta bot testing
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting Animetta MC Server..."
docker compose up -d

echo "Waiting for server to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:25565 > /dev/null 2>&1; then
        echo "MC Server is ready!"
        exit 0
    fi
    sleep 2
done

echo "Checking container logs..."
docker compose logs --tail=20
