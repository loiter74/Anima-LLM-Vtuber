#!/usr/bin/env python3
"""Batch collect Bilibili danmaku for training data.

This script collects danmaku from Bilibili trending videos in batches,
filters them for quality, and exports to multiple CSV files.

Usage:
    python scripts/collect_danmaku_batch.py --batch-count 10 --batch-size 100
    
    # With meme keywords
    python scripts/collect_danmaku_batch.py --batch-count 10 --batch-size 100 --keywords 草,awsl,哈哈哈
"""

import argparse
import asyncio
import csv
import logging
import sys
import time
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from animetta.services.bilibili import MemeCollector, CollectedDanmaku

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def collect_batch(
    batch_index: int,
    batch_size: int,
    min_length: int,
    max_length: int,
    meme_keywords: Optional[list[str]] = None,
) -> list[CollectedDanmaku]:
    """Collect a single batch of danmaku.
    
    Args:
        batch_index: Index of the current batch.
        batch_size: Number of danmaku to collect in this batch.
        min_length: Minimum character length.
        max_length: Maximum character length.
        meme_keywords: Optional list of meme keywords to filter by.
        
    Returns:
        List of collected danmaku.
    """
    config = {
        "max_videos": 20,
        "max_comments_per_video": 50,
        "min_comment_likes": 2,
        "request_delay": 0.5,
        "request_timeout": 300,
        "comment_timeout": 15,
        "concurrency": 3,
    }
    
    collector = MemeCollector(config=config)
    
    logger.info("Collecting batch %d/%d...", batch_index + 1, batch_size)
    
    danmaku_list = await collector.collect_danmaku_for_training(
        max_danmaku=batch_size,
        min_length=min_length,
        max_length=max_length,
        meme_keywords=meme_keywords,
    )
    
    logger.info("Batch %d: Collected %d danmaku", batch_index + 1, len(danmaku_list))
    return danmaku_list


def export_to_csv(danmaku_list: list[CollectedDanmaku], output_file: str) -> None:
    """Export danmaku to CSV file with UTF-8 BOM encoding.
    
    Args:
        danmaku_list: List of danmaku to export.
        output_file: Output file path.
    """
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        
        # Write header
        writer.writerow([
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
        ])
        
        # Write data
        for d in danmaku_list:
            writer.writerow([
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
            ])


async def collect_batch_all(
    batch_count: int,
    batch_size: int,
    min_length: int,
    max_length: int,
    meme_keywords: Optional[list[str]] = None,
    output_dir: str = "data/training",
) -> list[CollectedDanmaku]:
    """Collect all batches of danmaku.
    
    Args:
        batch_count: Number of batches to collect.
        batch_size: Number of danmaku per batch.
        min_length: Minimum character length.
        max_length: Maximum character length.
        meme_keywords: Optional list of meme keywords to filter by.
        output_dir: Output directory.
        
    Returns:
        List of all collected danmaku.
    """
    all_danmaku = []
    seen_content = set()
    
    for i in range(batch_count):
        logger.info("Starting batch %d/%d...", i + 1, batch_count)
        
        # Collect batch
        danmaku_list = await collect_batch(
            batch_index=i,
            batch_size=batch_size,
            min_length=min_length,
            max_length=max_length,
            meme_keywords=meme_keywords,
        )
        
        # Filter duplicates across batches
        unique_danmaku = []
        for d in danmaku_list:
            if d.content not in seen_content:
                seen_content.add(d.content)
                unique_danmaku.append(d)
        
        # Export to CSV
        output_file = f"{output_dir}/danmaku_batch_{i+1:02d}.csv"
        export_to_csv(unique_danmaku, output_file)
        logger.info("Exported batch %d to %s (%d unique)", i + 1, output_file, len(unique_danmaku))
        
        all_danmaku.extend(unique_danmaku)
        
        # Wait between batches
        if i < batch_count - 1:
            logger.info("Waiting 2 seconds before next batch...")
            await asyncio.sleep(2)
    
    return all_danmaku


def main():
    parser = argparse.ArgumentParser(
        description="Batch collect Bilibili danmaku for training data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect 10 batches of 100 danmaku each
  python scripts/collect_danmaku_batch.py --batch-count 10 --batch-size 100
  
  # Collect with meme keywords
  python scripts/collect_danmaku_batch.py --batch-count 10 --batch-size 100 --keywords 草,awsl,哈哈哈
  
  # Custom output directory
  python scripts/collect_danmaku_batch.py --batch-count 10 --batch-size 100 --output-dir data/training/danmaku
        """,
    )
    
    parser.add_argument(
        "--batch-count",
        type=int,
        default=10,
        help="Number of batches to collect (default: 10)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of danmaku per batch (default: 100)",
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
        "--output-dir",
        type=str,
        default="data/training",
        help="Output directory (default: data/training)",
    )
    
    args = parser.parse_args()
    
    # Parse keywords
    meme_keywords = None
    if args.keywords:
        meme_keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    
    # Run collection
    asyncio.run(collect_batch_all(
        batch_count=args.batch_count,
        batch_size=args.batch_size,
        min_length=args.min_length,
        max_length=args.max_length,
        meme_keywords=meme_keywords,
        output_dir=args.output_dir,
    ))


if __name__ == "__main__":
    main()
