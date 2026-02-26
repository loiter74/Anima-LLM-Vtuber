"""
Live2D 模型下载脚本
下载 Haru 模型用于测试
"""

import os
import sys
from pathlib import Path
import urllib.request
import json
import zipfile
import subprocess

# 模型配置
MODEL_NAME = "haru"
MODEL_URL = "https://github.com/guansss/pixi-live2d-display/raw/master/demo/assets/haru/haru_greeter_t03.model3.json"
MODEL_BASE_DIR = "https://github.com/guansss/pixi-live2d-display/raw/master/demo/assets/haru/"

def download_file(url, dest_path):
    """下载文件"""
    print(f"下载: {url}")
    print(f"到: {dest_path}")

    try:
        urllib.request.urlretrieve(url, dest_path)
        print(f"✅ 下载成功: {dest_path}")
        return True
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        return False

def main():
    """主函数"""
    # 确定目标目录
    script_dir = Path(__file__).parent.parent
    public_dir = script_dir / "frontend" / "public" / "live2d" / MODEL_NAME

    print(f"目标目录: {public_dir}")

    # 创建目录
    public_dir.mkdir(parents=True, exist_ok=True)

    # 需要下载的文件列表
    files = [
        "haru_greeter_t03.model3.json",
        "haru_greeter_t03.moc3",
        "haru_greeter_t03_2048.png",
        "haru_greeter_t03_2048.texture.json",
        "haru_greeter_t03.physics3.json",
    ]

    print(f"\n开始下载 Live2D 模型文件...\n")

    success_count = 0
    for file in files:
        url = f"{MODEL_BASE_DIR}{file}"
        dest_path = public_dir / file

        if dest_path.exists():
            print(f"⏭️ 文件已存在，跳过: {file}")
            success_count += 1
            continue

        if download_file(url, dest_path):
            success_count += 1

    print(f"\n{'='*60}")
    print(f"下载完成: {success_count}/{len(files)} 个文件")
    print(f"模型目录: {public_dir}")

    if success_count == len(files):
        print("\n✅ 所有文件下载完成！")
        print("\n下一步:")
        print("1. 启动后端: python -m anima.socketio_server")
        print("2. 启动前端: cd frontend && pnpm dev")
        print("3. 打开浏览器: http://localhost:3000")
        print("4. 打开测试页面: test_live2d_emotion.html")
    else:
        print("\n⚠️ 部分文件下载失败，请手动下载")
        print(f"访问: https://github.com/guansss/pixi-live2d-display/tree/master/demo/assets/haru")
        print(f"将文件下载到: {public_dir}")

if __name__ == "__main__":
    main()
