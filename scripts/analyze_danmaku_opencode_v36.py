#!/usr/bin/env python3
"""Analyze danmaku using OpenCode task system.

This script reads danmaku from CSV, analyzes with mimo and glm models
using OpenCode's task system, and merges results.

Usage:
    python scripts/analyze_danmaku_opencode_v36.py --input data/training/danmaku_analyzed.csv --output data/training/danmaku_final.csv
"""

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def read_csv(file_path: str) -> list[dict]:
    """Read CSV file and return list of dicts."""
    data = []
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    return data


def write_csv(data: list[dict], file_path: str) -> None:
    """Write list of dicts to CSV file."""
    if not data:
        return
    
    fieldnames = list(data[0].keys())
    
    with open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)


def create_batch_prompt(batch: list[dict], batch_index: int) -> str:
    """Create prompt for batch analysis.
    
    Args:
        batch: List of danmaku dicts.
        batch_index: Index of the batch.
        
    Returns:
        Prompt string for the batch.
    """
    prompt = f"""分析以下B站弹幕，解释其出现的语境和笑点类型。

请用JSON格式返回分析结果，格式为：
{{
    "results": [
        {{
            "index": 0,
            "content": "弹幕内容",
            "context": "这条弹幕可能出现的语境（50字以内）",
            "humor_type": "笑点类型（双关/谐音/反讽/玩梗/夸张/自嘲/其他）"
        }},
        ...
    ]
}}

要求：
1. context要简洁明了，说明弹幕出现的场景
2. humor_type要准确判断笑点类型
3. 如果无法判断，humor_type填"其他"
4. 只返回JSON，不要其他内容

弹幕列表（批次 {batch_index}）：
"""
    
    for i, row in enumerate(batch):
        prompt += f"{i}. {row['content']}\n"
    
    return prompt


def parse_batch_response(response: str, batch_size: int) -> list[dict]:
    """Parse batch response from LLM.
    
    Args:
        response: LLM response string.
        batch_size: Expected batch size.
        
    Returns:
        List of parsed results.
    """
    try:
        # Extract JSON from response
        response = response.strip()
        if response.startswith('```json'):
            response = response[7:]
        if response.endswith('```'):
            response = response[:-3]
        response = response.strip()
        
        data = json.loads(response)
        results = data.get('results', [])
        
        # Ensure we have enough results
        while len(results) < batch_size:
            results.append({
                'context': '分析失败',
                'humor_type': '其他'
            })
        
        return results[:batch_size]
        
    except (json.JSONDecodeError, AttributeError) as e:
        logger.warning("Failed to parse response: %s", e)
        return [{'context': '解析失败', 'humor_type': '其他'} for _ in range(batch_size)]


def merge_results(mimo_results: list[dict], glm_results: list[dict]) -> list[dict]:
    """Merge results from two models.
    
    Args:
        mimo_results: Results from mimo model.
        glm_results: Results from glm model.
        
    Returns:
        Merged results list.
    """
    merged = []
    
    for mimo, glm in zip(mimo_results, glm_results):
        # If both agree on humor_type, use it
        if mimo['humor_type'] == glm['humor_type']:
            humor_type = mimo['humor_type']
        else:
            # Choose the more specific one
            if mimo['humor_type'] != '其他':
                humor_type = mimo['humor_type']
            else:
                humor_type = glm['humor_type']
        
        # Choose the longer context (more detailed)
        if len(mimo['context']) > len(glm['context']):
            context = mimo['context']
        else:
            context = glm['context']
        
        merged.append({
            'context': context,
            'humor_type': humor_type
        })
    
    return merged


def main():
    parser = argparse.ArgumentParser(
        description="Analyze danmaku using OpenCode task system",
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
        "--batch-size",
        type=int,
        default=10,
        help="Batch size for analysis (default: 10)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run test mode with first batch only",
    )
    
    args = parser.parse_args()
    
    # Read input CSV
    logger.info("Reading input CSV: %s", args.input)
    data = read_csv(args.input)
    logger.info("Read %d danmaku", len(data))
    
    # Split into batches
    batches = []
    for i in range(0, len(data), args.batch_size):
        batch = data[i:i + args.batch_size]
        batches.append(batch)
    
    logger.info("Split into %d batches (size: %d)", len(batches), args.batch_size)
    
    # Test mode: only process first batch
    if args.test:
        batches = batches[:1]
        logger.info("Test mode: processing only first batch")
    
    # Process each batch
    all_mimo_results = []
    all_glm_results = []
    
    for batch_index, batch in enumerate(batches):
        logger.info("Processing batch %d/%d", batch_index + 1, len(batches))
        
        # Create prompt for this batch
        prompt = create_batch_prompt(batch, batch_index)
        
        # Save prompt to file for OpenCode task system
        prompt_file = f"data/training/batch_{batch_index}_prompt.txt"
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(prompt)
        
        logger.info("Saved prompt to %s", prompt_file)
        
        # Print sample
        print(f"\n[BATCH {batch_index}]")
        print(f"  Size: {len(batch)}")
        print(f"  Sample: {batch[0]['content'][:30]}...")
        print(f"  Prompt file: {prompt_file}")
    
    # Save batch info for OpenCode task system
    batch_info = {
        'total_rows': len(data),
        'batch_size': args.batch_size,
        'num_batches': len(batches),
        'test_mode': args.test,
        'batches': []
    }
    
    for i, batch in enumerate(batches):
        batch_info['batches'].append({
            'index': i,
            'size': len(batch),
            'prompt_file': f"data/training/batch_{i}_prompt.txt",
            'sample': [row['content'] for row in batch[:3]]
        })
    
    with open('data/training/batch_info.json', 'w', encoding='utf-8') as f:
        json.dump(batch_info, f, ensure_ascii=False, indent=2)
    
    logger.info("Saved batch info to data/training/batch_info.json")
    
    # Print summary
    print(f"\n[SUMMARY]")
    print(f"  Total rows: {len(data)}")
    print(f"  Batch size: {args.batch_size}")
    print(f"  Num batches: {len(batches)}")
    print(f"  Test mode: {args.test}")
    print(f"\n[NEXT] Use OpenCode task system to analyze batches:")
    print(f"  1. Read batch_info.json")
    print(f"  2. For each batch, create two tasks:")
    print(f"     - mimo task: analyze batch with mimo model")
    print(f"     - glm task: analyze batch with glm model")
    print(f"  3. Merge results")
    print(f"  4. Save to {args.output}")


if __name__ == "__main__":
    main()
