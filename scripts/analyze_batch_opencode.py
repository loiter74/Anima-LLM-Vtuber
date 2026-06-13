#!/usr/bin/env python3
"""Analyze a single batch of danmaku using OpenCode task system.

This script reads a batch of danmaku from a prompt file,
analyzes with mimo and glm models using OpenCode's task system,
and saves results to JSON.

Usage:
    python scripts/analyze_batch_opencode.py --batch-index 0 --prompt-file data/training/batch_0_prompt.txt --output data/training/batch_0_results.json
"""

import argparse
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


def read_prompt_file(file_path: str) -> str:
    """Read prompt from file.
    
    Args:
        file_path: Path to prompt file.
        
    Returns:
        Prompt string.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


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
        description="Analyze a single batch of danmaku using OpenCode task system",
    )
    
    parser.add_argument(
        "--batch-index",
        type=int,
        required=True,
        help="Index of the batch to analyze",
    )
    parser.add_argument(
        "--prompt-file",
        type=str,
        required=True,
        help="Path to prompt file",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output JSON file path",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Expected batch size (default: 10)",
    )
    
    args = parser.parse_args()
    
    # Read prompt file
    logger.info("Reading prompt file: %s", args.prompt_file)
    prompt = read_prompt_file(args.prompt_file)
    logger.info("Read prompt (%d chars)", len(prompt))
    
    # Print prompt summary
    print(f"\n[BATCH {args.batch_index}]")
    print(f"  Prompt file: {args.prompt_file}")
    print(f"  Prompt length: {len(prompt)} chars")
    print(f"  Expected batch size: {args.batch_size}")
    
    # Save prompt info for OpenCode task system
    prompt_info = {
        'batch_index': args.batch_index,
        'prompt_file': args.prompt_file,
        'prompt_length': len(prompt),
        'batch_size': args.batch_size,
        'output_file': args.output
    }
    
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(prompt_info, f, ensure_ascii=False, indent=2)
    
    logger.info("Saved prompt info to %s", args.output)
    
    # Print next steps
    print(f"\n[NEXT] Use OpenCode task system to analyze this batch:")
    print(f"  1. Read prompt from: {args.prompt_file}")
    print(f"  2. Create two tasks:")
    print(f"     - mimo task: analyze batch with mimo model")
    print(f"     - glm task: analyze batch with glm model")
    print(f"  3. Merge results")
    print(f"  4. Save to {args.output}")


if __name__ == "__main__":
    main()
