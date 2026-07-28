#!/usr/bin/env python3
"""Collect training danmaku from Bilibili trending videos."""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from animetta.services.bilibili import CollectedDanmaku, MemeCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def collect_danmaku(
    count: int = 100,
    min_length: int = 5,
    max_length: int = 20,
    meme_keywords: list[str] | None = None,
    output_file: str | None = None,
) -> list[CollectedDanmaku]:
    """Collect filtered training examples from trending videos."""

    collector = MemeCollector(
        config={
            "max_videos": 20,
            "max_comments_per_video": 50,
            "min_comment_likes": 2,
            "request_delay": 0.5,
            "request_timeout": 300,
            "comment_timeout": 15,
            "concurrency": 3,
        }
    )
    logger.info(
        "Starting training-data collection: count=%d length=%d-%d",
        count,
        min_length,
        max_length,
    )
    if meme_keywords:
        logger.info("Meme keywords: %s", meme_keywords)
    results = await collector.collect_danmaku_for_training(
        max_danmaku=count,
        min_length=min_length,
        max_length=max_length,
        meme_keywords=meme_keywords,
    )
    if output_file and results:
        export_to_csv(results, output_file)
    print_sample(results)
    return results


def export_to_csv(danmaku_list: list[CollectedDanmaku], output_file: str) -> None:
    """Export training examples using the historical CSV schema."""

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
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
        for item in danmaku_list:
            writer.writerow(
                [
                    item.content,
                    item.source_video,
                    item.source_type,
                    item.likes,
                    item.publish_time,
                    item.mode,
                    item.color,
                    item.is_meme,
                    item.meme_type,
                    f"{item.quality_score:.2f}",
                ]
            )
    logger.info("Exported %d danmaku to %s", len(danmaku_list), output_file)


def print_sample(danmaku_list: list[CollectedDanmaku], sample_size: int = 10) -> None:
    """Print the historical quality summary and a bounded sample."""

    if not danmaku_list:
        print("\n[ERROR] No danmaku collected!")
        return
    print(f"\n[OK] Collected {len(danmaku_list)} danmaku")
    print("[STATS] Quality distribution:")
    high = sum(1 for item in danmaku_list if item.quality_score >= 0.7)
    medium = sum(1 for item in danmaku_list if 0.4 <= item.quality_score < 0.7)
    low = sum(1 for item in danmaku_list if item.quality_score < 0.4)
    print(f"  - High quality (≥0.7): {high}")
    print(f"  - Medium quality (0.4-0.7): {medium}")
    print(f"  - Low quality (<0.4): {low}")
    meme_count = sum(1 for item in danmaku_list if item.is_meme)
    print(f"[MEME] Meme danmaku: {meme_count}/{len(danmaku_list)}")
    print(f"\n[SAMPLE] Sample danmaku (top {min(sample_size, len(danmaku_list))}):")
    for index, item in enumerate(danmaku_list[:sample_size], start=1):
        meme_tag = " [meme]" if item.is_meme else ""
        print(
            f"  {index:2d}. {item.content}{meme_tag} "
            f"(score: {item.quality_score:.2f}, likes: {item.likes})"
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the backward-compatible training collector CLI."""

    parser = argparse.ArgumentParser(description="Collect Bilibili danmaku for training data")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--min-length", type=int, default=5)
    parser.add_argument("--max-length", type=int, default=20)
    parser.add_argument("--keywords", type=str)
    parser.add_argument("--output", type=str)
    return parser


def main() -> None:
    """Run the historical-video training collector."""

    args = build_parser().parse_args()
    keywords = (
        [keyword.strip() for keyword in args.keywords.split(",") if keyword.strip()]
        if args.keywords
        else None
    )
    output_file = args.output or f"data/training/danmaku_{args.count}.csv"
    asyncio.run(
        collect_danmaku(
            count=args.count,
            min_length=args.min_length,
            max_length=args.max_length,
            meme_keywords=keywords,
            output_file=output_file,
        )
    )


if __name__ == "__main__":
    main()
