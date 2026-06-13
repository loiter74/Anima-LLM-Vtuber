#!/usr/bin/env python3
"""Analyze danmaku using cross-validation with multiple LLM models.

This script uses OpenCode's task functionality to analyze danmaku
with different LLM models (mimo and glm) and merge results.

Usage:
    python scripts/analyze_danmaku_cross.py --input data/training/danmaku_test_100.csv --output data/training/danmaku_analyzed.csv
"""

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def read_csv(file_path: str) -> list[dict]:
    """Read CSV file and return list of dicts.
    
    Args:
        file_path: Path to CSV file.
        
    Returns:
        List of dicts with CSV data.
    """
    data = []
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    return data


def write_csv(data: list[dict], file_path: str) -> None:
    """Write list of dicts to CSV file.
    
    Args:
        data: List of dicts to write.
        file_path: Output CSV file path.
    """
    if not data:
        return
    
    fieldnames = list(data[0].keys())
    
    with open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)


def create_analysis_prompt(content: str, source_video: str) -> str:
    """Create prompt for danmaku analysis.
    
    Args:
        content: Danmaku content.
        source_video: Source video BV ID.
        
    Returns:
        Analysis prompt string.
    """
    return f"""分析以下B站弹幕，解释其出现的语境和笑点类型。

弹幕内容：{content}
来源视频：{source_video}

请用JSON格式返回：
{{
    "context": "这条弹幕可能出现的语境（50字以内）",
    "humor_type": "笑点类型（双关/谐音/反讽/玩梗/夸张/自嘲/其他）"
}}

要求：
1. context要简洁明了，说明弹幕出现的场景
2. humor_type要准确判断笑点类型
3. 如果无法判断，humor_type填"其他"
4. 只返回JSON，不要其他内容"""


def parse_llm_response(response: str) -> dict:
    """Parse LLM response JSON.
    
    Args:
        response: LLM response string.
        
    Returns:
        Parsed dict with context and humor_type.
    """
    try:
        # Try to extract JSON from response
        response = response.strip()
        if response.startswith('```json'):
            response = response[7:]
        if response.endswith('```'):
            response = response[:-3]
        response = response.strip()
        
        data = json.loads(response)
        return {
            'context': data.get('context', '分析失败'),
            'humor_type': data.get('humor_type', '其他')
        }
    except (json.JSONDecodeError, AttributeError):
        return {
            'context': '解析失败',
            'humor_type': '其他'
        }


def merge_results(mimo_result: dict, glm_result: dict) -> dict:
    """Merge results from two models.
    
    Args:
        mimo_result: Result from mimo model.
        glm_result: Result from glm model.
        
    Returns:
        Merged result dict.
    """
    # If both agree on humor_type, use it
    if mimo_result['humor_type'] == glm_result['humor_type']:
        humor_type = mimo_result['humor_type']
    else:
        # Choose the more specific one
        if mimo_result['humor_type'] != '其他':
            humor_type = mimo_result['humor_type']
        else:
            humor_type = glm_result['humor_type']
    
    # Choose the longer context (more detailed)
    if len(mimo_result['context']) > len(glm_result['context']):
        context = mimo_result['context']
    else:
        context = glm_result['context']
    
    return {
        'context': context,
        'humor_type': humor_type
    }


def main():
    parser = argparse.ArgumentParser(
        description="Analyze danmaku using cross-validation with multiple LLM models",
    )
    
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="Input CSV file path",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output CSV file path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of danmaku to analyze (default: 100)",
    )
    
    args = parser.parse_args()
    
    # Read input CSV
    logger.info("Reading input CSV: %s", args.input)
    data = read_csv(args.input)
    logger.info("Read %d danmaku", len(data))
    
    # Limit data
    if args.limit:
        data = data[:args.limit]
        logger.info("Limited to %d danmaku", len(data))
    
    # Add new columns
    for row in data:
        row['mimo_context'] = ''
        row['mimo_humor_type'] = ''
        row['glm_context'] = ''
        row['glm_humor_type'] = ''
        row['final_context'] = ''
        row['final_humor_type'] = ''
    
    # Save to file for processing
    logger.info("Saving data for processing...")
    write_csv(data, args.output)
    logger.info("Saved to %s", args.output)
    logger.info("Total rows: %d", len(data))
    
    # Print sample
    print("\n[SAMPLE] First 5 rows:")
    for i, row in enumerate(data[:5]):
        print(f"  {i+1}. {row['content']}")
    
    print(f"\n[INFO] Total: {len(data)} rows")
    print(f"[INFO] Output: {args.output}")
    print(f"\n[NEXT] Run the analysis with OpenCode task system")


if __name__ == "__main__":
    main()
