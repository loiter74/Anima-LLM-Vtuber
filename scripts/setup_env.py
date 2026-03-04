#!/usr/bin/env python3
"""
快速环境配置脚本
Quick Environment Setup Script

自动检测当前环境并生成配置文件
"""

import sys
import os
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from anima.utils.env_helper import EnvHelper


def main():
    print("=" * 60)
    print("  Anima 快速环境配置工具")
    print("=" * 60)
    print()

    # 1. 检测环境
    print("🔍 检测运行环境...")
    env = EnvHelper.detect_environment()
    print(f"✅ 检测到环境: {env.upper()}")
    print()

    # 2. 获取数据目录
    print("📁 确定数据目录...")
    data_dir = EnvHelper.get_data_dir()
    print(f"✅ 数据目录: {data_dir}")

    # 检查目录是否存在
    if not data_dir.exists():
        print(f"⚠️  目录不存在，将创建: {data_dir}")
        response = input("是否创建? (y/n): ").strip().lower()
        if response == 'y':
            data_dir.mkdir(parents=True, exist_ok=True)
            print("✅ 目录创建成功")
        else:
            print("❌ 取消操作")
            return
    else:
        print(f"✅ 目录已存在")
    print()

    # 3. 生成环境配置
    print("📝 生成环境配置文件...")
    env_file = project_root / ".env"

    if env_file.exists():
        print(f"⚠️  .env 文件已存在: {env_file}")
        response = input("是否覆盖? (y/n): ").strip().lower()
        if response != 'y':
            print("❌ 取消操作")
            return

    EnvHelper.setup_env_file(overwrite=True)
    print()

    # 4. 更新配置文件
    print("🔧 更新配置文件...")
    config_file = project_root / "config" / "services" / "llm" / "local_lora.yaml"

    if config_file.exists():
        # 备份原配置
        backup_file = config_file.with_suffix(".yaml.bak")
        print(f"📦 备份原配置到: {backup_file}")
        config_file.replace(backup_file)

    # 复制模板
    template_file = project_root / "config" / "services" / "llm" / "local_lora.yaml.template"
    if template_file.exists():
        import shutil
        shutil.copy(template_file, config_file)
        print(f"✅ 已更新配置文件: {config_file}")
    else:
        print(f"⚠️  模板文件不存在: {template_file}")
    print()

    # 5. 显示配置摘要
    print("=" * 60)
    print("  配置摘要")
    print("=" * 60)
    config = EnvHelper.get_default_model_config()
    for key, value in config.items():
        print(f"  {key} = {value}")
    print("=" * 60)
    print()

    # 6. 下一步提示
    print("✅ 环境配置完成!")
    print()
    print("下一步:")
    print("  1. 检查 .env 文件中的路径是否正确")
    print("  2. 如果路径不同，请手动修改 .env 文件")
    print("  3. 启动服务:")
    print("     python -m anima.socketio_server")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ 操作已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
