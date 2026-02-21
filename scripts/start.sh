#!/bin/bash
# ============================================
# Anima Project Start Script (Linux/macOS)
# Enhanced with resource cleanup and graceful shutdown
# ============================================

set -e

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
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Default parameters
SKIP_BACKEND=false
SKIP_FRONTEND=false
INSTALL_DEPS=false

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
        --install)
            INSTALL_DEPS=true
            shift
            ;;
        -h|--help)
            echo "Usage: ./scripts/start.sh [Options]"
            echo ""
            echo "Options:"
            echo "  --skip-backend    Skip backend startup"
            echo "  --skip-frontend   Skip frontend startup"
            echo "  --install         Reinstall dependencies"
            echo "  -h, --help        Show help message"
            echo ""
            echo "Resource Management:"
            echo "  - Automatically stops existing processes on startup"
            echo "  - Cleans up temporary files and caches"
            echo "  - Graceful shutdown on script exit (SIGINT/SIGTERM)"
            exit 0
            ;;
        *)
            error "Unknown parameter: $1"
            ;;
    esac
done

echo ""
echo -e "${MAGENTA}========================================${NC}"
echo -e "${MAGENTA}  Anima Project Startup Script${NC}"
echo -e "${MAGENTA}========================================${NC}"
echo ""

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Check Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    error "Python not found, please install Python first"
fi

PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi

# Check package manager
if command -v pnpm &> /dev/null; then
    PKG_MANAGER="pnpm"
elif command -v npm &> /dev/null; then
    PKG_MANAGER="npm"
    warn "pnpm not found, using npm"
else
    error "Node.js not found, please install Node.js first"
fi

info "Package manager: $PKG_MANAGER"
info "Python: $PYTHON_CMD"
echo ""

# ============================================
# Resource Cleanup Functions
# ============================================

# Store PIDs
BACKEND_PID=""
FRONTEND_PID=""

stop_process_on_port() {
    local port=$1
    local service_name=$2
    local graceful=$3

    info "Checking for existing $service_name processes on port $port..."

    # Find process using the port
    local pids=$(lsof -ti:$port 2>/dev/null || true)

    if [ -n "$pids" ]; then
        warn "Found process(es) on port $port: $pids"

        for pid in $pids; do
            if ps -p $pid > /dev/null 2>&1; then
                if [ "$graceful" = "true" ]; then
                    info "Attempting graceful shutdown of PID $pid..."
                    kill -TERM $pid 2>/dev/null || true

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

                    # Check if still running
                    if ps -p $pid > /dev/null 2>&1; then
                        warn "Process $pid did not close gracefully, forcing..."
                        kill -KILL $pid 2>/dev/null || true
                    fi
                else
                    info "Force stopping process $pid..."
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

        # Final verification
        local still_listening=$(lsof -ti:$port 2>/dev/null || true)
        if [ -n "$still_listening" ]; then
            error "Port $port is still in use after cleanup"
            return 1
        else
            success "Port $port released successfully"
        fi
    else
        success "Port $port is free"
    fi

    return 0
}

stop_project_processes() {
    info "Checking for existing Anima processes..."

    local stopped=false

    # Stop Python processes (backend)
    local python_pids=$(pgrep -f "anima|socketio_server" 2>/dev/null || true)
    if [ -n "$python_pids" ]; then
        warn "Found Anima Python process(es): $python_pids"
        for pid in $python_pids; do
            info "Stopping Python process $pid..."
            kill -TERM $pid 2>/dev/null || true
            stopped=true
        done
    fi

    # Stop Node.js processes (frontend)
    local node_pids=$(pgrep -f "next|anima.*3000" 2>/dev/null || true)
    if [ -n "$node_pids" ]; then
        warn "Found Anima Node.js process(es): $node_pids"
        for pid in $node_pids; do
            info "Stopping Node.js process $pid..."
            kill -TERM $pid 2>/dev/null || true
            stopped=true
        done
    fi

    if [ "$stopped" = "true" ]; then
        sleep 1
        success "All existing Anima processes stopped"
    else
        success "No existing Anima processes found"
    fi

    return 0
}

clear_temp_files() {
    info "Cleaning up temporary files..."

    local cleaned=false

    # Clean Python cache
    if [ -d "$PROJECT_ROOT/src/__pycache__" ]; then
        rm -rf "$PROJECT_ROOT/src/__pycache__"
        info "Removed: Python cache"
        cleaned=true
    fi

    # Clean Next.js cache
    if [ -d "$PROJECT_ROOT/frontend/.next/cache" ]; then
        rm -rf "$PROJECT_ROOT/frontend/.next/cache"
        info "Removed: Next.js cache"
        cleaned=true
    fi

    # Clean temp files
    if [ -d "/tmp/anima_*" ]; then
        rm -rf /tmp/anima_*
        info "Removed: temp files"
        cleaned=true
    fi

    if [ "$cleaned" = "true" ]; then
        success "Temporary files cleaned up"
    else
        success "No temporary files to clean"
    fi
}

# ============================================
# Shutdown Handler
# ============================================

cleanup() {
    echo ""
    info "Initiating graceful shutdown..."

    # Stop frontend first (it depends on backend)
    if [ -n "$FRONTEND_PID" ] && ps -p $FRONTEND_PID > /dev/null 2>&1; then
        info "Stopping frontend (PID: $FRONTEND_PID)..."
        kill -TERM $FRONTEND_PID 2>/dev/null || true

        # Wait for graceful shutdown
        local waited=0
        while [ $waited -lt 5 ]; do
            if ! ps -p $FRONTEND_PID > /dev/null 2>&1; then
                success "Frontend stopped gracefully"
                break
            fi
            sleep 1
            waited=$((waited + 1))
        done

        # Force if needed
        if ps -p $FRONTEND_PID > /dev/null 2>&1; then
            warn "Frontend did not stop gracefully, forcing..."
            kill -KILL $FRONTEND_PID 2>/dev/null || true
        fi
    fi

    # Stop backend
    if [ -n "$BACKEND_PID" ] && ps -p $BACKEND_PID > /dev/null 2>&1; then
        info "Stopping backend (PID: $BACKEND_PID)..."
        kill -TERM $BACKEND_PID 2>/dev/null || true

        # Wait for graceful shutdown
        local waited=0
        while [ $waited -lt 5 ]; do
            if ! ps -p $BACKEND_PID > /dev/null 2>&1; then
                success "Backend stopped gracefully"
                break
            fi
            sleep 1
            waited=$((waited + 1))
        done

        # Force if needed
        if ps -p $BACKEND_PID > /dev/null 2>&1; then
            warn "Backend did not stop gracefully, forcing..."
            kill -KILL $BACKEND_PID 2>/dev/null || true
        fi
    fi

    # Additional port cleanup
    stop_process_on_port 3000 "Frontend" false
    stop_process_on_port 12394 "Backend" false

    success "All services stopped"
    exit 0
}

# Register signal handlers
trap cleanup SIGINT SIGTERM EXIT

# ============================================
# Phase 1: Stop Existing Services
# ============================================

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  Phase 1: Stopping Existing Services${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

# Stop backend port
if [ "$SKIP_BACKEND" = "false" ]; then
    if ! stop_process_on_port 12394 "Backend" true; then
        error "Failed to stop existing backend services"
    fi
fi

# Stop frontend port
if [ "$SKIP_FRONTEND" = "false" ]; then
    if ! stop_process_on_port 3000 "Frontend" true; then
        error "Failed to stop existing frontend services"
    fi
fi

# Stop any remaining project processes
stop_project_processes

echo ""
success "All existing services stopped"
echo ""

# ============================================
# Phase 2: Clean Temporary Files
# ============================================

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  Phase 2: Cleaning Resources${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

clear_temp_files

echo ""

# ============================================
# Phase 3: Install Dependencies (Optional)
# ============================================

if [ "$INSTALL_DEPS" = "true" ]; then
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}  Phase 3: Installing Dependencies${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""

    info "Installing backend dependencies..."
    $PYTHON_CMD -m pip install -r requirements.txt

    info "Installing frontend dependencies..."
    cd "$PROJECT_ROOT/frontend"
    $PKG_MANAGER install
    cd "$PROJECT_ROOT"
    echo ""
fi

# ============================================
# Phase 4: Start Services
# ============================================

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Phase 4: Starting Services${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Start backend
if [ "$SKIP_BACKEND" = "false" ]; then
    info "Starting backend server (port 12394)..."
    cd "$PROJECT_ROOT/src"
    $PYTHON_CMD -m anima.socketio_server &
    BACKEND_PID=$!
    cd "$PROJECT_ROOT"
    success "Backend started: http://localhost:12394 (PID: $BACKEND_PID)"

    info "Waiting for backend to start..."
    sleep 3

    # Verify backend is running
    if ! ps -p $BACKEND_PID > /dev/null 2>&1; then
        error "Backend failed to start. Check logs for details."
    fi
else
    warn "Skipping backend"
fi

# Start frontend
if [ "$SKIP_FRONTEND" = "false" ]; then
    info "Starting frontend dev server..."
    cd "$PROJECT_ROOT/frontend"
    NEXT_PRIVATE_BENCHMARK_ENABLED=false $PKG_MANAGER dev &
    FRONTEND_PID=$!
    cd "$PROJECT_ROOT"
    success "Frontend started: http://localhost:3000 (PID: $FRONTEND_PID)"
else
    warn "Skipping frontend"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Startup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

if [ "$SKIP_BACKEND" = "false" ]; then
    echo -e "  Backend: ${CYAN}http://localhost:12394${NC}"
fi
if [ "$SKIP_FRONTEND" = "false" ]; then
    echo -e "  Frontend: ${CYAN}http://localhost:3000${NC}"
fi

echo ""
echo -e "  ${YELLOW}Press Ctrl+C to stop all services${NC}"
echo ""

# Wait for processes and monitor
while true; do
    # Check if processes are still running
    if [ -n "$BACKEND_PID" ]; then
        if ! ps -p $BACKEND_PID > /dev/null 2>&1; then
            warn "Backend process has stopped unexpectedly"
            BACKEND_PID=""
        fi
    fi

    if [ -n "$FRONTEND_PID" ]; then
        if ! ps -p $FRONTEND_PID > /dev/null 2>&1; then
            warn "Frontend process has stopped unexpectedly"
            FRONTEND_PID=""
        fi
    fi

    # Exit if both stopped
    if [ -z "$BACKEND_PID" ] && [ -z "$FRONTEND_PID" ]; then
        warn "All services have stopped"
        break
    fi

    sleep 1
done
