#!/bin/bash
# ============================================
# Anima 项目启动脚本 (Linux/macOS)
# 同时启动后端和前端服务
# ============================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# 颜色输出函数
info() { echo -e "${CYAN}[信息]${NC} $1"; }
success() { echo -e "${GREEN}[成功]${NC} $1"; }
warn() { echo -e "${YELLOW}[警告]${NC} $1"; }
error() { echo -e "${RED}[错误]${NC} $1"; exit 1; }

# 默认参数
SKIP_BACKEND=false
SKIP_FRONTEND=false
INSTALL_DEPS=false

# 解析参数
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
            echo "用法: ./scripts/start.sh [选项]"
            echo ""
            echo "选项:"
            echo "  --skip-backend    跳过后端启动"
            echo "  --skip-frontend   跳过前端启动"
            echo "  --install         重新安装依赖"
            echo "  -h, --help        显示帮助信息"
            exit 0
            ;;
        *)
            error "未知参数: $1"
            ;;
    esac
done

echo ""
echo -e "${MAGENTA}========================================${NC}"
echo -e "${MAGENTA}  Anima 项目启动脚本${NC}"
echo -e "${MAGENTA}========================================${NC}"
echo ""

# 获取项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# 检查 Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    error "未找到 Python，请先安装 Python"
fi

PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi

# 检查包管理器
if command -v pnpm &> /dev/null; then
    PKG_MANAGER="pnpm"
elif command -v npm &> /dev/null; then
    PKG_MANAGER="npm"
    warn "未找到 pnpm，使用 npm"
else
    error "未找到 Node.js，请先安装 Node.js"
fi

info "使用包管理器: $PKG_MANAGER"
info "使用 Python: $PYTHON_CMD"
echo ""

# 安装依赖
if [ "$INSTALL_DEPS" = true ]; then
    info "安装后端依赖..."
    pip install -r requirements.txt
    
    info "安装前端依赖..."
    cd frontend
    $PKG_MANAGER install
    cd ..
    echo ""
fi

# 存储进程 ID
BACKEND_PID=""
FRONTEND_PID=""

# 清理函数
cleanup() {
    echo ""
    info "正在停止服务..."
    if [ -n "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
        info "后端服务已停止"
    fi
    if [ -n "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null || true
        info "前端服务已停止"
    fi
    exit 0
}

# 捕获退出信号
trap cleanup SIGINT SIGTERM

# 启动后端
if [ "$SKIP_BACKEND" = false ]; then
    info "启动后端服务器 (端口 12394)..."
    cd "$PROJECT_ROOT/src"
    $PYTHON_CMD -m anima.socketio_server &
    BACKEND_PID=$!
    cd "$PROJECT_ROOT"
    success "后端服务已启动: http://localhost:12394 (PID: $BACKEND_PID)"
    
    info "等待后端启动..."
    sleep 3
else
    warn "跳过后端服务"
fi

# 启动前端
if [ "$SKIP_FRONTEND" = false ]; then
    info "启动前端开发服务器..."
    cd "$PROJECT_ROOT/frontend"
    NEXT_PRIVATE_BENCHMARK_ENABLED=false $PKG_MANAGER dev &
    FRONTEND_PID=$!
    cd "$PROJECT_ROOT"
    success "前端服务已启动: http://localhost:3000 (PID: $FRONTEND_PID)"
else
    warn "跳过前端服务"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  启动完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

if [ "$SKIP_BACKEND" = false ]; then
    echo -e "  后端: ${CYAN}http://localhost:12394${NC}"
fi
if [ "$SKIP_FRONTEND" = false ]; then
    echo -e "  前端: ${CYAN}http://localhost:3000${NC}"
fi

echo ""
echo -e "  ${YELLOW}按 Ctrl+C 停止所有服务${NC}"
echo ""

# 等待子进程
wait