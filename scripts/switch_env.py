#!/usr/bin/env python3
"""
环境配置切换脚本 (跨平台)
Usage: python scripts/switch_env.py [windows|wsl|linux]
"""

import sys
import shutil
from pathlib import Path
from datetime import datetime
import platform


def print_header(text: str):
    """打印标题"""
    if platform.system() == "Windows":
        # 使用 ANSI 颜色代码
        colors = {"cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m", "red": "\033[31m", "reset": "\033[0m"}
        print(f"{colors['cyan']}=========================================={colors['reset']}")
        print(f"{colors['cyan']}  {text}{colors['reset']}")
        print(f"{colors['cyan']}=========================================={colors['reset']}")
    else:
        print("=" * 40)
        print(f"  {text}")
        print("=" * 40)


def print_success(text: str):
    """打印成功信息"""
    if platform.system() == "Windows":
        print(f"\033[32m{text}\033[0m")
    else:
        print(text)


def print_warning(text: str):
    """打印警告信息"""
    if platform.system() == "Windows":
        print(f"\033[33m{text}\033[0m")
    else:
        print(text)


def print_error(text: str):
    """打印错误信息"""
    if platform.system() == "Windows":
        print(f"\033[31m{text}\033[0m")
    else:
        print(text)


def main():
    """主函数"""
    if len(sys.argv) < 2:
        env_name = "wsl"
    else:
        env_name = sys.argv[1].lower()

    # 项目路径
    project_root = Path(__file__).parent.parent
    env_file = project_root / ".env"

    print_header("Anima 环境配置切换工具")
    print(f"项目根目录: {project_root}\n")

    # 备份现有 .env 文件
    if env_file.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = project_root / f".env.backup.{timestamp}"
        print(f"📦 备份当前 .env 到: {backup_file}")
        shutil.copy(env_file, backup_file)

    # 根据环境选择配置源
    env_files = {
        "windows": ".env.windows.example",
        "win": ".env.windows.example",
        "wsl": ".env.wsl.example",
        "linux": ".env.linux.example"
    }

    if env_name not in env_files:
        print_error(f"❌ 错误: 不支持的环境 '{env_name}'")
        print("\n用法: python switch_env.py [windows|wsl|linux]")
        print("\n示例:")
        print("  python switch_env.py windows  # Windows 环境")
        print("  python switch_env.py wsl      # WSL 环境")
        print("  python switch_env.py linux    # 纯 Linux 环境")
        sys.exit(1)

    source_file = project_root / env_files[env_name]

    # 显示切换目标
    env_labels = {
        "windows": "Windows",
        "wsl": "WSL",
        "linux": "Linux"
    }
    print(f"🪟 切换到 {env_labels[env_name]} 环境")

    # 检查源文件是否存在
    if not source_file.exists():
        print_error(f"❌ 错误: 配置文件不存在: {source_file}")
        print("\n请先创建环境配置文件：")
        print("  - .env.windows.example (Windows)")
        print("  - .env.wsl.example (WSL)")
        print("  - .env.linux.example (Linux)")
        sys.exit(1)

    # 复制配置
    shutil.copy(source_file, env_file)
    print_success(f"✅ 已复制配置: {source_file} -> {env_file}")
    print()

    # 显示当前配置
    print_warning("⚠️  请检查并修改 .env 文件中的路径配置：")
    print()
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip().startswith('ANIMA_'):
                print(f"  {line.rstrip()}")
    print()

    print_success("✅ 环境切换完成！")
    print()
    print("下一步:")
    print("  1. 编辑 .env 文件，确认路径正确")
    print("  2. 启动服务: python -m anima.socketio_server")


if __name__ == "__main__":
    main()
