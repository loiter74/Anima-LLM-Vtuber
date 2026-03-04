#!/bin/bash
# 环境配置切换脚本 (Unix/WSL)
# Usage: ./scripts/switch_env.sh [windows|wsl|linux]

set -e

ENV_NAME=${1:-"wsl"}
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

echo "=========================================="
echo "  Anima 环境配置切换工具"
echo "=========================================="
echo "当前目录: $PROJECT_ROOT"
echo ""

# 备份现有 .env 文件
if [ -f "$ENV_FILE" ]; then
    BACKUP_FILE="$PROJECT_ROOT/.env.backup.$(date +%Y%m%d_%H%M%S)"
    echo "📦 备份当前 .env 到: $BACKUP_FILE"
    cp "$ENV_FILE" "$BACKUP_FILE"
fi

# 根据环境选择配置源
case "$ENV_NAME" in
    windows|win)
        SOURCE_FILE="$PROJECT_ROOT/.env.windows.example"
        echo "🪟 切换到 Windows 环境"
        ;;
    wsl)
        SOURCE_FILE="$PROJECT_ROOT/.env.wsl.example"
        echo "🐧 切换到 WSL 环境"
        ;;
    linux)
        SOURCE_FILE="$PROJECT_ROOT/.env.linux.example"
        echo "🐧 切换到 Linux 环境"
        ;;
    *)
        echo "❌ 错误: 不支持的环境 '$ENV_NAME'"
        echo ""
        echo "用法: $0 [windows|wsl|linux]"
        echo ""
        echo "示例:"
        echo "  $0 windows  # Windows 环境"
        echo "  $0 wsl      # WSL 环境"
        echo "  $0 linux    # 纯 Linux 环境"
        exit 1
        ;;
esac

# 检查源文件是否存在
if [ ! -f "$SOURCE_FILE" ]; then
    echo "❌ 错误: 配置文件不存在: $SOURCE_FILE"
    echo ""
    echo "请先创建环境配置文件："
    echo "  - .env.windows.example (Windows)"
    echo "  - .env.wsl.example (WSL)"
    echo "  - .env.linux.example (Linux)"
    exit 1
fi

# 复制配置
cp "$SOURCE_FILE" "$ENV_FILE"
echo "✅ 已复制配置: $SOURCE_FILE -> $ENV_FILE"
echo ""

# 检查并提示编辑
echo "⚠️  请检查并修改 .env 文件中的路径配置："
echo ""
grep -E "^ANIMA_" "$ENV_FILE" | sed 's/^/  /' || true
echo ""
echo "✅ 环境切换完成！"
echo ""
echo "下一步:"
echo "  1. 编辑 .env 文件，确认路径正确"
echo "  2. 启动服务: python -m anima.socketio_server"
