#!/usr/bin/env python3
"""Collect Bilibili danmaku for training data.

This script collects danmaku from Bilibili trending videos,
filters them for quality, and exports to CSV format.

Usage:
    python scripts/collect_danmaku.py --count 100 --output data/training/danmaku.csv

    # With meme keywords
    python scripts/collect_danmaku.py --count 100 --keywords 草,awsl,哈哈哈

    # Custom length filter
    python scripts/collect_danmaku.py --count 100 --min-length 5 --max-length 20
"""

import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from animetta.services.bilibili import CollectedDanmaku, MemeCollector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def collect_danmaku(
    count: int = 100,
    min_length: int = 5,
    max_length: int = 20,
    meme_keywords: Optional[list[str]] = None,
    output_file: Optional[str] = None,
) -> list[CollectedDanmaku]:
    """Collect danmaku from Bilibili trending videos.

    Args:
        count: Number of danmaku to collect.
        min_length: Minimum character length.
        max_length: Maximum character length.
        meme_keywords: Optional list of meme keywords to filter by.
        output_file: Optional output file path.

    Returns:
        List of collected danmaku.
    """
    # Initialize collector with default config
    config = {
        "max_videos": 20,  # Collect from 20 videos
        "max_comments_per_video": 50,
        "min_comment_likes": 2,
        "request_delay": 0.5,  # Be nice to Bilibili servers
        "request_timeout": 300,  # 5 minutes timeout
        "comment_timeout": 15,
        "concurrency": 3,  # Limit concurrent requests
    }

    collector = MemeCollector(config=config)

    logger.info("Starting danmaku collection...")
    logger.info("Target: %d danmaku, length: %d-%d chars", count, min_length, max_length)
    if meme_keywords:
        logger.info("Meme keywords: %s", meme_keywords)

    # Collect danmaku
    danmaku_list = await collector.collect_danmaku_for_training(
        max_danmaku=count,
        min_length=min_length,
        max_length=max_length,
        meme_keywords=meme_keywords,
    )

    logger.info("Collected %d danmaku", len(danmaku_list))

    # Export to CSV if output file specified
    if output_file and danmaku_list:
        export_to_csv(danmaku_list, output_file)
        logger.info("Exported to %s", output_file)

    # Print sample
    print_sample(danmaku_list)

    return danmaku_list


def export_to_csv(danmaku_list: list[CollectedDanmaku], output_file: str) -> None:
    """Export danmaku to CSV file.

    Args:
        danmaku_list: List of danmaku to export.
        output_file: Output file path.
    """
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Write header
        writer.writerow(
            [
                "content",
                "source_video",
                "source_type",
                "likes",
                "publish_time",
                "mode",
                "color",
                "is_meme",
                "meme_type",
                "quality_score",
            ]
        )

        # Write data
        for d in danmaku_list:
            writer.writerow(
                [
                    d.content,
                    d.source_video,
                    d.source_type,
                    d.likes,
                    d.publish_time,
                    d.mode,
                    d.color,
                    d.is_meme,
                    d.meme_type,
                    f"{d.quality_score:.2f}",
                ]
            )

    logger.info("Exported %d danmaku to %s", len(danmaku_list), output_file)


def print_sample(danmaku_list: list[CollectedDanmaku], sample_size: int = 10) -> None:
    """Print a sample of collected danmaku.

    Args:
        danmaku_list: List of danmaku.
        sample_size: Number of samples to print.
    """
    if not danmaku_list:
        print("\n[ERROR] No danmaku collected!")
        return

    print(f"\n[OK] Collected {len(danmaku_list)} danmaku")
    print(f"[STATS] Quality distribution:")

    # Calculate quality distribution
    high_quality = sum(1 for d in danmaku_list if d.quality_score >= 0.7)
    medium_quality = sum(1 for d in danmaku_list if 0.4 <= d.quality_score < 0.7)
    low_quality = sum(1 for d in danmaku_list if d.quality_score < 0.4)

    print(f"  - High quality (≥0.7): {high_quality}")
    print(f"  - Medium quality (0.4-0.7): {medium_quality}")
    print(f"  - Low quality (<0.4): {low_quality}")

    # Calculate meme distribution
    meme_count = sum(1 for d in danmaku_list if d.is_meme)
    print(f"[MEME] Meme danmaku: {meme_count}/{len(danmaku_list)}")

    # Print sample
    print(f"\n[SAMPLE] Sample danmaku (top {min(sample_size, len(danmaku_list))}):")
    for i, d in enumerate(danmaku_list[:sample_size]):
        meme_tag = " [meme]" if d.is_meme else ""
        print(
            f"  {i + 1:2d}. {d.content}{meme_tag} (score: {d.quality_score:.2f}, likes: {d.likes})"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Collect Bilibili danmaku for training data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect 100 danmaku
  python scripts/collect_danmaku.py --count 100
  
  # Collect with meme keywords
  python scripts/collect_danmaku.py --count 100 --keywords 草,awsl,哈哈哈
  
  # Custom length filter
  python scripts/collect_danmaku.py --count 100 --min-length 5 --max-length 20
  
  # Export to specific file
  python scripts/collect_danmaku.py --count 100 --output data/training/danmaku.csv
        """,
    )

    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of danmaku to collect (default: 100)",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=5,
        help="Minimum character length (default: 5)",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=20,
        help="Maximum character length (default: 20)",
    )
    parser.add_argument(
        "--keywords",
        type=str,
        help="Comma-separated list of meme keywords (e.g., 草,awsl,哈哈哈)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output CSV file path (default: data/training/danmaku_{count}.csv)",
    )

    args = parser.parse_args()

    # Parse keywords
    meme_keywords = None
    if args.keywords:
        meme_keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    # Set default output file
    output_file = args.output
    if not output_file:
        output_file = f"data/training/danmaku_{args.count}.csv"

    # Run collection
    asyncio.run(
        collect_danmaku(
            count=args.count,
            min_length=args.min_length,
            max_length=args.max_length,
            meme_keywords=meme_keywords,
            output_file=output_file,
        )
    )


if __name__ == "__main__":
    main()
