#!/usr/bin/env python3
"""Collect Bilibili danmaku from specific UP主 videos.

This script collects danmaku from specific UP主's videos,
filters them for quality, and exports to CSV files.

Usage:
    python scripts/collect_danmaku_by_up.py --up 王老菊 --count 100
    
    # Multiple UP主
    python scripts/collect_danmaku_by_up.py --up 王老菊,稚嫩的魔法师 --count 100
    
    # With output file
    python scripts/collect_danmaku_by_up.py --up 王老菊 --count 100 --output data/training/wanglaoju.csv
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

from animetta.services.bilibili.api import fetch_video_danmaku

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def search_up_videos(up_name: str, max_videos: int = 20) -> list[dict]:
    """Search for videos by UP主 name.
    
    Args:
        up_name: UP主 name to search for.
        max_videos: Maximum number of videos to return.
        
    Returns:
        List of video dicts.
    """
    try:
        import bilibili_api
        search_module = bilibili_api.search
        sync_func = bilibili_api.sync
        
        # Search for videos by UP主
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: sync_func(search_module.search(
                keyword=up_name,
                page=1,
            )),
        )
        
        if not result or "result" not in result:
            return []
        
        videos = []
        for item in result["result"]:
            if isinstance(item, dict) and item.get("result_type") == "video":
                data = item.get("data", [])
                if isinstance(data, list):
                    for video in data[:max_videos]:
                        if isinstance(video, dict) and "bvid" in video:
                            videos.append(video)
        
        return videos
        
    except Exception as e:
        logger.warning("Failed to search videos for UP主 %s: %s", up_name, e)
        return []


async def collect_danmaku_from_video(bvid: str, max_count: int = 100) -> list[dict]:
    """Collect danmaku from a specific video.
    
    Args:
        bvid: Video BV ID.
        max_count: Maximum number of danmaku to return.
        
    Returns:
        List of danmaku dicts.
    """
    try:
        danmaku_list = await fetch_video_danmaku(
            bvid=bvid,
            max_count=max_count,
            timeout=15.0,
        )
        return danmaku_list
    except Exception as e:
        logger.warning("Failed to collect danmaku from %s: %s", bvid, e)
        return []


def filter_danmaku(
    danmaku_list: list[dict],
    min_length: int = 5,
    max_length: int = 20,
    meme_keywords: Optional[list[str]] = None,
) -> list[dict]:
    """Filter danmaku for quality.
    
    Args:
        danmaku_list: Raw danmaku list.
        min_length: Minimum character length.
        max_length: Maximum character length.
        meme_keywords: Optional list of meme keywords to filter by.
        
    Returns:
        Filtered list of danmaku dicts.
    """
    filtered = []
    
    for d in danmaku_list:
        content = d.get("content", "")
        
        # Filter by length
        if not (min_length <= len(content) <= max_length):
            continue
        
        # Filter by meme keywords if provided
        if meme_keywords:
            content_lower = content.lower()
            has_keyword = False
            for keyword in meme_keywords:
                if keyword.lower() in content_lower:
                    has_keyword = True
                    break
            if not has_keyword:
                continue
        
        filtered.append(d)
    
    return filtered


async def collect_danmaku_by_up(
    up_names: list[str],
    count: int,
    min_length: int,
    max_length: int,
    meme_keywords: Optional[list[str]] = None,
) -> list[dict]:
    """Collect danmaku from specific UP主's videos.
    
    Args:
        up_names: List of UP主 names.
        count: Number of danmaku to collect.
        min_length: Minimum character length.
        max_length: Maximum character length.
        meme_keywords: Optional list of meme keywords to filter by.
        
    Returns:
        List of collected danmaku dicts.
    """
    all_danmaku = []
    seen_content = set()
    
    for up_name in up_names:
        logger.info("Searching videos for UP主: %s", up_name)
        
        # Search for videos
        videos = await search_up_videos(up_name, max_videos=10)
        logger.info("Found %d videos for UP主: %s", len(videos), up_name)
        
        if not videos:
            continue
        
        # Collect danmaku from each video
        for video in videos:
            bvid = video.get("bvid", "")
            if not bvid:
                continue
            
            title = video.get("title", "")
            logger.info("Collecting danmaku from video: %s (%s)", bvid, title)
            
            try:
                # Get danmaku from video
                raw_danmaku = await collect_danmaku_from_video(bvid, max_count=200)
                logger.info("Got %d raw danmaku from %s", len(raw_danmaku), bvid)
                
                # Filter danmaku
                filtered_danmaku = filter_danmaku(
                    raw_danmaku,
                    min_length=min_length,
                    max_length=max_length,
                    meme_keywords=meme_keywords,
                )
                logger.info("Filtered to %d danmaku from %s", len(filtered_danmaku), bvid)
                
                # Add to collection (avoid duplicates)
                for d in filtered_danmaku:
                    content = d.get("content", "")
                    if content not in seen_content:
                        seen_content.add(content)
                        all_danmaku.append(d)
                
                logger.info("Total collected: %d unique danmaku", len(all_danmaku))
                
                # Check if we have enough
                if len(all_danmaku) >= count:
                    break
                    
            except Exception as e:
                logger.warning("Failed to collect danmaku from %s: %s", bvid, e)
                continue
        
        # Check if we have enough
        if len(all_danmaku) >= count:
            break
    
    return all_danmaku[:count]


def export_to_csv(danmaku_list: list[dict], output_file: str) -> None:
    """Export danmaku to CSV file with UTF-8 BOM encoding.
    
    Args:
        danmaku_list: List of danmaku dicts to export.
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
        ])
        
        # Write data
        for d in danmaku_list:
            writer.writerow([
                d.get("content", ""),
                d.get("source_video", ""),
                d.get("source_type", "video"),
                d.get("likes", 0),
                d.get("publish_time", ""),
                d.get("mode", 1),
                d.get("color", 16777215),
            ])


def main():
    parser = argparse.ArgumentParser(
        description="Collect Bilibili danmaku from specific UP主 videos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect from 王老菊
  python scripts/collect_danmaku_by_up.py --up 王老菊 --count 100
  
  # Collect from multiple UP主
  python scripts/collect_danmaku_by_up.py --up 王老菊,稚嫩的魔法师 --count 100
  
  # With meme keywords
  python scripts/collect_danmaku_by_up.py --up 王老菊 --count 100 --keywords 草,awsl
        """,
    )
    
    parser.add_argument(
        "--up",
        type=str,
        required=True,
        help="Comma-separated list of UP主 names (e.g., 王老菊,稚嫩的魔法师)",
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
        help="Output CSV file path",
    )
    
    args = parser.parse_args()
    
    # Parse UP主 names
    up_names = [name.strip() for name in args.up.split(",") if name.strip()]
    
    # Parse keywords
    meme_keywords = None
    if args.keywords:
        meme_keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    
    # Set default output file
    output_file = args.output
    if not output_file:
        up_str = "_".join(up_names[:3])  # Use first 3 UP主 names
        output_file = f"data/training/danmaku_{up_str}.csv"
    
    # Run collection
    danmaku_list = asyncio.run(collect_danmaku_by_up(
        up_names=up_names,
        count=args.count,
        min_length=args.min_length,
        max_length=args.max_length,
        meme_keywords=meme_keywords,
    ))
    
    # Export to CSV
    export_to_csv(danmaku_list, output_file)
    print(f"Exported {len(danmaku_list)} danmaku to {output_file}")


if __name__ == "__main__":
    main()
