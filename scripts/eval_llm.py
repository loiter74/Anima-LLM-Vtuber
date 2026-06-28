"""Multi-LLM comparison script.

Sends identical prompts to multiple LLM providers and compares
responses using semantic similarity scoring.

Usage:
    PYTHONPATH=src python scripts/eval_llm.py \
        --prompts scripts/eval_prompts.txt \
        --providers deepseek,openai

Prompts file format (tab-separated):
    prompt text\treference answer

Requires: sentence-transformers (pip install -r requirements-local-ai.txt)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from loguru import logger
from openai import AsyncOpenAI
from sentence_transformers import SentenceTransformer

# ── Provider configs ────────────────────────────────────────────────

PROVIDER_CONFIGS: dict[str, dict[str, str]] = {
    "deepseek": {
        "env_key": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "openai": {
        "env_key": "OPENAI_API_KEY",
        "base_url": None,  # default OpenAI endpoint
        "model": "gpt-4o-mini",
    },
    "glm": {
        "env_key": "GLM_API_KEY",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    },
    "mimo": {
        "env_key": "MIMO_API_KEY",
        "base_url": "https://api.mimo.ai/v1",
        "model": "mimo-latest",
    },
}

# ── Data classes ────────────────────────────────────────────────────


@dataclass
class PromptEntry:
    prompt: str
    reference: str


@dataclass
class EvalResult:
    provider: str
    prompt: str
    reference: str
    response: str
    latency_s: float
    similarity: float
    error: str | None = None


@dataclass
class ProviderSummary:
    provider: str
    avg_similarity: float
    avg_latency: float
    quality_per_sec: float
    total_prompts: int
    errors: int


# ── Similarity scoring ─────────────────────────────────────────────


class SimilarityScorer:
    """Computes cosine similarity using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        logger.info(f"Loading similarity model: {model_name}")
        self.model = SentenceTransformer(model_name)

    def score(self, text_a: str, text_b: str) -> float:
        """Return cosine similarity in [0.0, 1.0]."""
        embeddings = self.model.encode([text_a, text_b], convert_to_numpy=True)
        a, b = embeddings[0], embeddings[1]
        dot = float(np.dot(a, b))
        norm = float(np.linalg.norm(a) * np.linalg.norm(b))
        if norm == 0:
            return 0.0
        return max(0.0, min(1.0, dot / norm))


# ── LLM calling ────────────────────────────────────────────────────


async def call_llm(
    provider: str,
    prompt: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> tuple[str, float]:
    """Call a provider and return (response_text, latency_seconds)."""
    cfg = PROVIDER_CONFIGS.get(provider)
    if cfg is None:
        raise ValueError(f"Unknown provider: {provider}. Available: {list(PROVIDER_CONFIGS)}")

    api_key = os.getenv(cfg["env_key"], "")
    if not api_key:
        raise RuntimeError(f"Missing env var {cfg['env_key']} for provider {provider}")

    kwargs: dict = {"api_key": api_key}
    if cfg["base_url"]:
        kwargs["base_url"] = cfg["base_url"]

    client = AsyncOpenAI(**kwargs)

    t0 = time.perf_counter()
    resp = await client.chat.completions.create(
        model=cfg["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    latency = time.perf_counter() - t0

    text = resp.choices[0].message.content or ""
    return text.strip(), latency


# ── File parsing ────────────────────────────────────────────────────


def load_prompts(path: Path) -> list[PromptEntry]:
    """Load prompts file. Each line: prompt<TAB>reference_answer."""
    entries: list[PromptEntry] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            logger.warning(f"Line {i}: expected tab-separated prompt and reference, skipping")
            continue
        entries.append(PromptEntry(prompt=parts[0].strip(), reference=parts[1].strip()))
    return entries


# ── Evaluation ──────────────────────────────────────────────────────


async def evaluate_provider(
    provider: str,
    prompts: list[PromptEntry],
    scorer: SimilarityScorer,
) -> list[EvalResult]:
    """Evaluate one provider against all prompts."""
    results: list[EvalResult] = []
    for entry in prompts:
        try:
            response, latency = await call_llm(provider, entry.prompt)
            similarity = scorer.score(response, entry.reference)
            results.append(
                EvalResult(
                    provider=provider,
                    prompt=entry.prompt,
                    reference=entry.reference,
                    response=response,
                    latency_s=latency,
                    similarity=similarity,
                )
            )
            logger.info(
                f"[{provider}] sim={similarity:.3f} lat={latency:.2f}s | {entry.prompt[:40]}..."
            )
        except Exception as e:
            logger.error(f"[{provider}] Error: {e}")
            results.append(
                EvalResult(
                    provider=provider,
                    prompt=entry.prompt,
                    reference=entry.reference,
                    response="",
                    latency_s=0.0,
                    similarity=0.0,
                    error=str(e),
                )
            )
    return results


def summarize(results: list[EvalResult]) -> list[ProviderSummary]:
    """Compute per-provider summary stats."""
    by_provider: dict[str, list[EvalResult]] = {}
    for r in results:
        by_provider.setdefault(r.provider, []).append(r)

    summaries: list[ProviderSummary] = []
    for provider, rs in by_provider.items():
        valid = [r for r in rs if r.error is None]
        errors = len(rs) - len(valid)
        avg_sim = sum(r.similarity for r in valid) / len(valid) if valid else 0.0
        avg_lat = sum(r.latency_s for r in valid) / len(valid) if valid else 0.0
        qps = avg_sim / avg_lat if avg_lat > 0 else 0.0
        summaries.append(
            ProviderSummary(
                provider=provider,
                avg_similarity=round(avg_sim, 4),
                avg_latency=round(avg_lat, 3),
                quality_per_sec=round(qps, 4),
                total_prompts=len(rs),
                errors=errors,
            )
        )
    return sorted(summaries, key=lambda s: s.avg_similarity, reverse=True)


# ── Output formatting ───────────────────────────────────────────────


def format_markdown(summaries: list[ProviderSummary], results: list[EvalResult]) -> str:
    """Render evaluation results as Markdown."""
    lines = [
        "# LLM Evaluation Results\n",
        "## Summary\n",
        "| Provider | Avg Similarity | Avg Latency (s) | Quality/sec | Prompts | Errors |",
        "|----------|---------------|-----------------|-------------|---------|--------|",
    ]
    for s in summaries:
        lines.append(
            f"| {s.provider} | {s.avg_similarity:.4f} | {s.avg_latency:.3f} "
            f"| {s.quality_per_sec:.4f} | {s.total_prompts} | {s.errors} |"
        )

    lines.append("\n## Detailed Results\n")
    for r in results:
        lines.append(f"### [{r.provider}] {r.prompt[:60]}")
        if r.error:
            lines.append(f"**Error:** {r.error}\n")
        else:
            lines.append(f"- **Similarity:** {r.similarity:.4f}")
            lines.append(f"- **Latency:** {r.latency_s:.3f}s")
            lines.append(f"- **Response:** {r.response[:200]}{'...' if len(r.response) > 200 else ''}")
            lines.append(f"- **Reference:** {r.reference[:200]}\n")

    return "\n".join(lines)


def format_json(summaries: list[ProviderSummary], results: list[EvalResult]) -> str:
    """Render evaluation results as JSON."""
    return json.dumps(
        {
            "summary": [
                {
                    "provider": s.provider,
                    "avg_similarity": s.avg_similarity,
                    "avg_latency_s": s.avg_latency,
                    "quality_per_sec": s.quality_per_sec,
                    "total_prompts": s.total_prompts,
                    "errors": s.errors,
                }
                for s in summaries
            ],
            "results": [
                {
                    "provider": r.provider,
                    "prompt": r.prompt,
                    "reference": r.reference,
                    "response": r.response,
                    "latency_s": round(r.latency_s, 3),
                    "similarity": round(r.similarity, 4),
                    "error": r.error,
                }
                for r in results
            ],
        },
        indent=2,
        ensure_ascii=False,
    )


# ── CLI ─────────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser(description="Compare multiple LLM providers")
    parser.add_argument("--prompts", required=True, help="Path to prompts file (tab-separated)")
    parser.add_argument(
        "--providers",
        required=True,
        help="Comma-separated provider names (e.g. deepseek,openai)",
    )
    parser.add_argument("--output", default=None, help="Output JSON file path (optional)")
    parser.add_argument("--temperature", type=float, default=0.7, help="LLM temperature")
    parser.add_argument("--max-tokens", type=int, default=1024, help="Max tokens per response")
    args = parser.parse_args()

    load_dotenv()

    # Parse inputs
    prompts_path = Path(args.prompts)
    if not prompts_path.exists():
        logger.error(f"Prompts file not found: {prompts_path}")
        sys.exit(1)

    providers = [p.strip() for p in args.providers.split(",")]
    prompts = load_prompts(prompts_path)

    if not prompts:
        logger.error("No valid prompts found in file")
        sys.exit(1)

    logger.info(f"Loaded {len(prompts)} prompts, evaluating {len(providers)} providers")

    # Initialize scorer
    scorer = SimilarityScorer()

    # Run evaluation (providers in parallel, prompts sequential per provider)
    all_results: list[EvalResult] = []
    tasks = [evaluate_provider(p, prompts, scorer) for p in providers]
    provider_results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(provider_results):
        if isinstance(result, Exception):
            logger.error(f"Provider {providers[i]} failed: {result}")
        else:
            all_results.extend(result)

    # Summarize
    summaries = summarize(all_results)

    # Output
    md = format_markdown(summaries, all_results)
    print(md)

    json_out = format_json(summaries, all_results)
    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json_out, encoding="utf-8")
        logger.info(f"JSON results written to {out_path}")
    else:
        print("\n--- JSON ---")
        print(json_out)


if __name__ == "__main__":
    asyncio.run(main())
