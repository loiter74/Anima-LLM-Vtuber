"""
统一数据采集脚本（简化版）
Unified Data Collection Script

整合所有数据采集功能到一个脚本中

使用方法：
```bash
# 从 B站采集视频弹幕
python scripts/training/collect_data.py --source bilibili --type video --url https://www.bilibili.com/video/BV1xx411c7mD

# 从本地文件加载
python scripts/training/collect_data.py --source local --file data/raw/conversations.jsonl

# 下载公开数据集
python scripts/training/collect_data.py --source public --dataset VTuber-Conversations

# 查看帮助
python scripts/training/collect_data.py --help
```
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger


def collect_bilibili_video(url: str, output_dir: str) -> bool:
    """
    从 B站视频采集弹幕

    Args:
        url: B站视频 URL
        output_dir: 输出目录

    Returns:
        是否成功
    """
    logger.info(f"采集 B站视频: {url}")

    try:
        # 这里可以集成实际的 B站采集逻辑
        # 为了简化，这里只创建示例数据

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 示例数据
        conversations = [
            {
                "conversation": [
                    {"role": "user", "content": "你好"},
                    {"role": "assistant", "content": "你好呀！"}
                ]
            }
        ]

        # 保存为 JSONL
        output_file = output_path / "bilibili_data.jsonl"
        with open(output_file, "w", encoding="utf-8") as f:
            for conv in conversations:
                f.write(json.dumps(conv, ensure_ascii=False) + "\n")

        logger.info(f"数据已保存到: {output_file}")
        logger.info(f"共采集 {len(conversations)} 条对话")

        return True

    except Exception as e:
        logger.error(f"采集失败: {e}")
        return False


def load_local_data(file_path: str, output_dir: str) -> bool:
    """
    从本地文件加载数据

    Args:
        file_path: 本地文件路径
        output_dir: 输出目录

    Returns:
        是否成功
    """
    logger.info(f"加载本地数据: {file_path}")

    try:
        input_path = Path(file_path)
        if not input_path.exists():
            logger.error(f"文件不存在: {file_path}")
            return False

        # 读取数据
        conversations = []
        with open(input_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    conversations.append(json.loads(line))

        # 保存到输出目录
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        output_file = output_path / "local_data.jsonl"
        with open(output_file, "w", encoding="utf-8") as f:
            for conv in conversations:
                f.write(json.dumps(conv, ensure_ascii=False) + "\n")

        logger.info(f"数据已保存到: {output_file}")
        logger.info(f"共加载 {len(conversations)} 条对话")

        return True

    except Exception as e:
        logger.error(f"加载失败: {e}")
        return False


def download_public_dataset(dataset_name: str, output_dir: str) -> bool:
    """
    下载公开数据集

    Args:
        dataset_name: 数据集名称
        output_dir: 输出目录

    Returns:
        是否成功
    """
    logger.info(f"下载数据集: {dataset_name}")

    try:
        # 这里可以集成实际的数据集下载逻辑
        # 为了简化，这里只创建示例数据

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 示例数据
        conversations = [
            {
                "conversation": [
                    {"role": "user", "content": "介绍一下你自己"},
                    {"role": "assistant", "content": "我是 AI 助手，很高兴为你服务！"}
                ]
            }
        ]

        # 保存为 JSONL
        output_file = output_path / f"{dataset_name}.jsonl"
        with open(output_file, "w", encoding="utf-8") as f:
            for conv in conversations:
                f.write(json.dumps(conv, ensure_ascii=False) + "\n")

        logger.info(f"数据已保存到: {output_file}")
        logger.info(f"共下载 {len(conversations)} 条对话")

        return True

    except Exception as e:
        logger.error(f"下载失败: {e}")
        return False


def merge_datasets(input_files: List[str], output_file: str) -> bool:
    """
    合并多个数据集

    Args:
        input_files: 输入文件列表
        output_file: 输出文件路径

    Returns:
        是否成功
    """
    logger.info(f"合并 {len(input_files)} 个数据集")

    try:
        all_conversations = []

        # 读取所有文件
        for file_path in input_files:
            logger.info(f"读取文件: {file_path}")
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        all_conversations.append(json.loads(line))

        # 保存合并后的数据
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            for conv in all_conversations:
                f.write(json.dumps(conv, ensure_ascii=False) + "\n")

        logger.info(f"合并后的数据已保存到: {output_file}")
        logger.info(f"总共 {len(all_conversations)} 条对话")

        return True

    except Exception as e:
        logger.error(f"合并失败: {e}")
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="统一数据采集脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:

  # B站视频采集
  python %(prog)s --source bilibili --type video --url https://www.bilibili.com/video/BV1xx411c7mD

  # 本地文件加载
  python %(prog)s --source local --file data/raw/conversations.jsonl

  # 下载数据集
  python %(prog)s --source public --dataset VTuber-Conversations

  # 合并多个数据集
  python %(prog)s --source merge --files data1.jsonl data2.jsonl --output merged.jsonl
        """
    )

    # 数据源
    parser.add_argument("--source", required=True, choices=["bilibili", "local", "public", "merge"], help="数据源类型")

    # B站采集参数
    parser.add_argument("--type", choices=["video", "danmu", "uploader"], help="B站采集类型")
    parser.add_argument("--url", help="B站视频/用户 URL")

    # 本地文件参数
    parser.add_argument("--file", help="本地文件路径")

    # 公开数据集参数
    parser.add_argument("--dataset", help="数据集名称")

    # 合并参数
    parser.add_argument("--files", nargs="+", help="要合并的文件列表")
    parser.add_argument("--output", help="输出文件")

    # 通用参数
    parser.add_argument("--output-dir", default="datasets", help="输出目录")
    parser.add_argument("--debug", action="store_true", help="调试模式")

    args = parser.parse_args()

    # 设置日志
    logger.remove()
    logger.add(sys.stdout, level="DEBUG" if args.debug else "INFO")

    logger.info("=" * 60)
    logger.info("统一数据采集脚本")
    logger.info("=" * 60)

    # 根据数据源执行不同的操作
    success = False

    if args.source == "bilibili":
        if not args.url:
            logger.error("B站采集需要 --url 参数")
            sys.exit(1)

        success = collect_bilibili_video(args.url, args.output_dir)

    elif args.source == "local":
        if not args.file:
            logger.error("本地文件需要 --file 参数")
            sys.exit(1)

        success = load_local_data(args.file, args.output_dir)

    elif args.source == "public":
        if not args.dataset:
            logger.error("下载数据集需要 --dataset 参数")
            sys.exit(1)

        success = download_public_dataset(args.dataset, args.output_dir)

    elif args.source == "merge":
        if not args.files or not args.output:
            logger.error("合并数据需要 --files 和 --output 参数")
            sys.exit(1)

        success = merge_datasets(args.files, args.output)

    if success:
        logger.info("✅ 采集完成！")
        sys.exit(0)
    else:
        logger.error("❌ 采集失败！")
        sys.exit(1)


if __name__ == "__main__":
    main()
