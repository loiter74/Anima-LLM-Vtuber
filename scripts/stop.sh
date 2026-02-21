#!/bin/bash
# ============================================
# Anima Project Stop Script (Linux/macOS)
# Enhanced with graceful shutdown and resource verification
# ============================================

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

# Output functions
info() { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Default parameters
SKIP_BACKEND=false
SKIP_FRONTEND=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-backend)
            SKIP_BACKEND=true
            shift
            ;;
        --skip-frontend)
            SKIP_FRONTEND=true
            shift
            ;;
        -h|--help)
            echo "Usage: ./scripts/stop.sh [Options]"
            echo ""
            echo "Options:"
            echo "  --skip-backend     Skip backend stop"
            echo "  --skip-frontend    Skip frontend stop"
            echo "  -h, --help         Show help message"
            echo ""
            echo "Features:"
            echo "  - Graceful shutdown with SIGTERM first"
            echo "  - Falls back to SIGKILL if needed"
            echo "  - Verifies port release"
            echo "  - Cleans up temporary files"
            exit 0
            ;;
        *)
            error "Unknown parameter: $1"
            ;;
    esac
done

echo ""
echo -e "${MAGENTA}========================================${NC}"
echo -e "${MAGENTA}  Anima Project Stop Script${NC}"
echo -e "${MAGENTA}========================================${NC}"
echo ""

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# ============================================
# Stop Functions
# ============================================

stop_service_on_port() {
    local port=$1
    local service_name=$2

    info "Stopping $service_name (port $port)..."

    local stopped=false
    local pids=$(lsof -ti:$port 2>/dev/null || true)

    if [ -n "$pids" ]; then
        info "Found process(es) on port $port: $pids"

        for pid in $pids; do
            if ps -p $pid > /dev/null 2>&1; then
                info "Attempting graceful shutdown of PID $pid..."
                kill -TERM $pid 2>/dev/null || true
                stopped=true

                # Wait for graceful shutdown
                local max_wait=5
                local waited=0
                while [ $waited -lt $max_wait ]; do
                    if ! ps -p $pid > /dev/null 2>&1; then
                        success "Process $pid closed gracefully"
                        break
                    fi
                    sleep 1
                    waited=$((waited + 1))
                done

                # Force if still running
                if ps -p $pid > /dev/null 2>&1; then
                    warn "Process $pid did not close gracefully, forcing..."
                    kill -KILL $pid 2>/dev/null || true
                fi
            fi
        done

        # Wait for port to be released
        local max_wait=5
        local waited=0
        while [ $waited -lt $max_wait ]; do
            if ! lsof -ti:$port &>/dev/null; then
                break
            fi
            sleep 1
            waited=$((waited + 1))
        done
    fi

    return $stopped
}

stop_processes_by_name() {
    local process_name=$1
    shift
    local patterns=("$@")

    local stopped=false

    for pattern in "${patterns[@]}"; do
        local pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            for pid in $pids; do
                if ps -p $pid > /dev/null 2>&1; then
                    info "Stopping $process_name process $pid..."
                    kill -TERM $pid 2>/dev/null || true

                    # Wait for graceful shutdown
                    local max_wait=3
                    local waited=0
                    while [ $waited -lt $max_wait ]; do
                        if ! ps -p $pid > /dev/null 2>&1; then
                            break
                        fi
                        sleep 1
                        waited=$((waited + 1))
                    done

                    # Force if still running
                    if ps -p $pid > /dev/null 2>&1; then
                        kill -KILL $pid 2>/dev/null || true
                    fi

                    stopped=true
                fi
            done
        fi
    done

    return $stopped
}

clear_temp_files() {
    info "Cleaning up temporary files..."

    local cleaned=false

    # Clean Python cache
    if [ -d "$PROJECT_ROOT/src/__pycache__" ]; then
        rm -rf "$PROJECT_ROOT/src/__pycache__"
        cleaned=true
    fi

    # Clean Next.js cache
    if [ -d "$PROJECT_ROOT/frontend/.next/cache" ]; then
        rm -rf "$PROJECT_ROOT/frontend/.next/cache"
        cleaned=true
    fi

    # Clean temp files
    if ls /tmp/anima_* 1> /dev/null 2>&1; then
        rm -rf /tmp/anima_*
        cleaned=true
    fi

    if [ "$cleaned" = "true" ]; then
        success "Temporary files cleaned up"
    fi
}

# ============================================
# Phase 1: Stop Services
# ============================================

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  Phase 1: Stopping Services${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

backend_stopped=false
frontend_stopped=false

# Stop frontend first (it depends on backend)
if [ "$SKIP_FRONTEND" = "false" ]; then
    if stop_service_on_port 3000 "Frontend"; then
        frontend_stopped=true
        success "Frontend service stopped"
    else
        warn "No frontend service found on port 3000"
    fi

    # Also stop by process name
    stop_processes_by_name "node" "next" "anima" "3000"
else
    warn "Skipping frontend"
fi

echo ""

# Stop backend
if [ "$SKIP_BACKEND" = "false" ]; then
    if stop_service_on_port 12394 "Backend"; then
        backend_stopped=true
        success "Backend service stopped"
    else
        warn "No backend service found on port 12394"
    fi

    # Also stop by process name
    stop_processes_by_name "python" "socketio_server" "anima"
else
    warn "Skipping backend"
fi

echo ""

# ============================================
# Phase 2: Verify Ports Released
# ============================================

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  Phase 2: Verifying Port Release${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

backend_port_in_use=false
frontend_port_in_use=false

if [ "$SKIP_BACKEND" = "false" ]; then
    backend_port=$(lsof -ti:12394 2>/dev/null || true)
    if [ -n "$backend_port" ]; then
        error "Port 12394 (backend) is still in use"
        backend_port_in_use=true

        # Show which process is holding the port
        for pid in $backend_port; do
            if ps -p $pid > /dev/null 2>&1; then
                warn "  Held by PID: $pid"
                warn "  Command: $(ps -p $pid -o command=)"
            fi
        done
    else
        success "Port 12394 (backend): Released"
    fi
fi

if [ "$SKIP_FRONTEND" = "false" ]; then
    frontend_port=$(lsof -ti:3000 2>/dev/null || true)
    if [ -n "$frontend_port" ]; then
        error "Port 3000 (frontend) is still in use"
        frontend_port_in_use=true

        # Show which process is holding the port
        for pid in $frontend_port; do
            if ps -p $pid > /dev/null 2>&1; then
                warn "  Held by PID: $pid"
                warn "  Command: $(ps -p $pid -o command=)"
            fi
        done
    else
        success "Port 3000 (frontend): Released"
    fi
fi

echo ""

# ============================================
# Phase 3: Clean Temporary Files
# ============================================

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  Phase 3: Cleaning Resources${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

clear_temp_files

echo ""

# ============================================
# Summary
# ============================================

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Stop Summary${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

if [ "$backend_stopped" = "true" ] || [ "$frontend_stopped" = "true" ]; then
    success "Services stopped successfully"
else
    warn "No services were stopped"
fi

if [ "$backend_port_in_use" = "true" ] || [ "$frontend_port_in_use" = "true" ]; then
    error "Some ports are still in use - you may need to:"
    echo -e "  ${GRAY}1. Check for other instances holding the ports${NC}"
    echo -e "  ${GRAY}2. Reboot to clear all system resources${NC}"
    echo -e "  ${GRAY}3. Manually kill the processes shown above${NC}"
    exit 1
else
    success "All resources released successfully"
fi

echo ""
