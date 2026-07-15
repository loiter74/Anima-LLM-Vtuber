#!/usr/bin/env python3
"""RAG Evaluation Reporter — JSON, Markdown, and Chart output generators.

Functions:
    save_json_results(data, output_dir)  → results.json (per-query detail)
    save_json_summary(data, output_dir)  → summary.json (aggregates)
    save_markdown_report(data, output_dir) → report.md (Jinja2 template)
    save_charts(results_list, output_dir)  → charts/*.png (matplotlib)
    generate_all(data, output_dir)         → calls all four above
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ── Matplotlib (non-interactive backend) ──────────────────────────────
try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _HAS_MPL = True
except ImportError:
    _HAS_MPL = False
    logger.info("matplotlib not available — charts will be skipped")

# ── Jinja2 ─────────────────────────────────────────────────────────────
try:
    import jinja2

    _HAS_JINJA2 = True
except ImportError:
    _HAS_JINJA2 = False
    logger.info("jinja2 not available — markdown report will use basic formatting")


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def get_git_commit() -> str:
    """Get current git commit (short hash), or 'unknown'."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


# ═══════════════════════════════════════════════════════════════════════
# A. JSON detailed results
# ═══════════════════════════════════════════════════════════════════════


def save_json_results(data: dict[str, Any], output_dir: Path) -> Path:
    """Save full per-query results as results.json."""
    _ensure_dir(output_dir)
    out_path = output_dir / "results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    logger.info("Saved results.json → %s", out_path)
    return out_path


# ═══════════════════════════════════════════════════════════════════════
# B. JSON summary
# ═══════════════════════════════════════════════════════════════════════


def save_json_summary(data: dict[str, Any], output_dir: Path) -> Path:
    """Save compact summary as summary.json."""
    _ensure_dir(output_dir)
    out_path = output_dir / "summary.json"

    summary = {
        "config": {
            "name": data["config"]["name"],
            "vector_weight": data["config"].get("vector_weight"),
            "keyword_weight": data["config"].get("keyword_weight"),
            "embedding_model": data["config"].get("embedding_model"),
            "target_tokens": data["config"].get("target_tokens"),
            "fuzzy_enabled": data["config"].get("fuzzy_enabled"),
        },
        "timestamp": data.get("timestamp", ""),
        "git_commit": data.get("git_commit", ""),
        "summary": data.get("summary", {}),
        "per_category": data.get("per_category", {}),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    logger.info("Saved summary.json → %s", out_path)
    return out_path


# ═══════════════════════════════════════════════════════════════════════
# C. Markdown report
# ═══════════════════════════════════════════════════════════════════════

_MD_TEMPLATE = """
# RAG Evaluation Report — {{ config_name }}

**Generated:** {{ timestamp }}
**Git commit:** `{{ git_commit }}`

---

## Experiment Configuration

| Parameter | Value |
|-----------|-------|
| Vector weight | {{ config.vector_weight }} |
| Keyword weight | {{ config.keyword_weight }} |
| Embedding model | `{{ config.embedding_model }}` |
| Target tokens | {{ config.target_tokens }} |
| Overlap tokens | {{ config.overlap_tokens }} |
| Fuzzy layer | {{ config.fuzzy_enabled }} |
| Max results (k) | {{ config.max_results }} |
{% if config.description %}
**Description:** {{ config.description }}
{% endif %}

---

## Overall Metrics (k={{ summary.k }})

| Metric | Value |
|--------|-------|
| Recall@k | {{ "%.4f" | format(summary.recall_at_k) }} |
| Precision@k | {{ "%.4f" | format(summary.precision_at_k) }} |
| MRR | {{ "%.4f" | format(summary.mrr) }} |
| NDCG@k | {{ "%.4f" | format(summary.ndcg_at_k) }} |
| Chunk Diversity | {{ "%.4f" | format(summary.chunk_diversity) }} |
| Total Queries | {{ summary.total_queries }} |

---

## Latency Distribution

| Percentile | Latency (ms) |
|------------|-------------|
| P50 (median) | {{ "%.1f" | format(latency.p50) }} |
| P75 | {{ "%.1f" | format(latency.p75) }} |
| P90 | {{ "%.1f" | format(latency.p90) }} |
| P95 | {{ "%.1f" | format(latency.p95) }} |
| P99 | {{ "%.1f" | format(latency.p99) }} |
| Mean | {{ "%.1f" | format(latency.mean) }} |
| Min | {{ "%.1f" | format(latency.min) }} |
| Max | {{ "%.1f" | format(latency.max) }} |

---

## Per-Category Breakdown

| Category | Recall@k | Precision@k | MRR | NDCG@k | Avg Latency (ms) | Count |
|----------|----------|------------|-----|--------|-----------------|-------|
{% for cat, metrics in per_category.items() %}
| {{ cat }} | {{ "%.4f" | format(metrics.recall_at_k) }} | {{ "%.4f" | format(metrics.precision_at_k) }} | {{ "%.4f" | format(metrics.mrr) }} | {{ "%.4f" | format(metrics.ndcg_at_k) }} | {{ "%.1f" | format(metrics.latency_mean_ms) }} | {{ metrics.count }} |
{% endfor %}

---

## Per-Difficulty Breakdown

| Difficulty | Queries | Avg Recall@k |
|------------|---------|-------------|
{% for diff in difficulty_breakdown %}
| {{ diff.level }} | {{ diff.count }} | {{ "%.4f" | format(diff.avg_recall) }} |
{% endfor %}

---

## Notes

- All metrics computed at **k={{ summary.k }}**
- Chunk identifiers are `(path, start_line, end_line)` tuples
- Latency measured from query submission to results returned
- FuzzyLayer enabled: {{ config.fuzzy_enabled }}
"""


def save_markdown_report(data: dict[str, Any], output_dir: Path) -> Path:
    """Generate report.md using Jinja2 (fallback: basic Python format)."""
    _ensure_dir(output_dir)
    out_path = output_dir / "report.md"

    config = data.get("config", {})
    summary = data.get("summary", {})
    per_category = data.get("per_category", {})
    latency = data.get("latency_percentiles", {})
    per_query = data.get("per_query", [])

    # ── Difficulty breakdown ──
    difficulty_recall: dict[str, list[float]] = {}
    difficulty_count: dict[str, int] = {}
    for q in per_query:
        d = q.get("difficulty", "unknown")
        difficulty_recall.setdefault(d, []).append(q["recall_at_k"])
        difficulty_count[d] = difficulty_count.get(d, 0) + 1
    difficulty_breakdown = sorted(
        [
            {"level": d, "count": difficulty_count[d], "avg_recall": sum(vals) / len(vals)}
            for d, vals in difficulty_recall.items()
        ],
        key=lambda x: x["level"],
    )

    ctx = {
        "config_name": config.get("name", "unknown"),
        "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "git_commit": data.get("git_commit", ""),
        "config": config,
        "summary": summary,
        "per_category": per_category,
        "latency": latency,
        "difficulty_breakdown": difficulty_breakdown,
    }

    from jinja2 import Template as Jinja2Template

    template = Jinja2Template(_MD_TEMPLATE)
    report = template.render(**ctx)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info("Saved report.md → %s", out_path)
    return out_path


# ═══════════════════════════════════════════════════════════════════════
# D. Charts (matplotlib)
# ═══════════════════════════════════════════════════════════════════════


def save_charts(
    all_results: list[dict[str, Any]],
    output_dir: Path,
) -> None:
    """Generate comparison charts: recall comparison + latency distribution.

    Args:
        all_results: List of per-config result dicts (as returned by EvalRunner.run()).
        output_dir: Directory to save charts/ into.
    """
    if not _HAS_MPL:
        logger.warning("matplotlib not installed — skipping charts")
        return

    charts_dir = _ensure_dir(output_dir)

    # ── Chart 1: Recall Comparison (grouped bar chart) ──────────
    _save_recall_comparison(all_results, charts_dir)

    # ── Chart 2: Latency Distribution (histogram) ──────────────
    _save_latency_distribution(all_results, charts_dir)

    plt.close("all")


def _save_recall_comparison(
    all_results: list[dict[str, Any]],
    charts_dir: Path,
) -> None:
    """Grouped bar chart: one bar per config per category."""
    if not all_results:
        return

    # Collect all categories across all configs
    all_categories: set[str] = set()
    for r in all_results:
        all_categories.update(r.get("per_category", {}).keys())
    categories = sorted(all_categories)

    if not categories:
        logger.warning("No categories found for recall comparison chart")
        return

    config_names = [r["config"]["name"] for r in all_results]
    n_configs = len(config_names)
    n_cats = len(categories)

    x = range(n_cats)
    bar_width = 0.8 / max(n_configs, 1)

    fig, ax = plt.subplots(figsize=(max(10, n_cats * 2), 6))

    for i, result in enumerate(all_results):
        name = config_names[i]
        pc = result.get("per_category", {})
        values = [pc.get(cat, {}).get("recall_at_k", 0.0) for cat in categories]
        offset = (i - n_configs / 2 + 0.5) * bar_width
        ax.bar([p + offset for p in x], values, bar_width, label=name)

    ax.set_xlabel("Category")
    ax.set_ylabel("Recall@k")
    ax.set_title("Recall@k Comparison by Category")
    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=30, ha="right")
    ax.legend(loc="lower right", fontsize="small")
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    out_path = charts_dir / "recall_comparison.png"
    fig.savefig(out_path, dpi=150)
    logger.info("Saved recall_comparison.png → %s", out_path)


def _save_latency_distribution(
    all_results: list[dict[str, Any]],
    charts_dir: Path,
) -> None:
    """Histogram of per-query latencies, overlay all configs.

    If only one config, show single histogram. If multiple, show overlaid.
    """
    if not all_results:
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    for result in all_results:
        config_name = result["config"]["name"]
        latencies = [q["latency_ms"] for q in result.get("per_query", [])]
        if not latencies:
            continue
        ax.hist(latencies, bins=30, alpha=0.5, label=config_name)

    ax.set_xlabel("Latency (ms)")
    ax.set_ylabel("Query Count")
    ax.set_title("Per-Query Latency Distribution")
    ax.legend(loc="upper right", fontsize="small")
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    out_path = charts_dir / "latency_distribution.png"
    fig.savefig(out_path, dpi=150)
    logger.info("Saved latency_distribution.png → %s", out_path)


# ═══════════════════════════════════════════════════════════════════════
# E. Convenience — generate all outputs
# ═══════════════════════════════════════════════════════════════════════


def generate_all(data: dict[str, Any], output_dir: str | Path) -> dict[str, Path]:
    """Generate all outputs for a single result: JSON, summary, markdown, charts.

    Args:
        data: Result dict from EvalRunner.run().
        output_dir: Target directory.

    Returns:
        Dict mapping output type → file path.
    """
    out = _ensure_dir(Path(output_dir))
    paths = {}

    paths["results_json"] = save_json_results(data, out)
    paths["summary_json"] = save_json_summary(data, out)
    paths["report_md"] = save_markdown_report(data, out)
    save_charts([data], out / "charts")
    paths["charts_dir"] = out / "charts"

    return paths


# ═══════════════════════════════════════════════════════════════════════
# CLI (standalone — for regenerating reports from saved results.json)
# ═══════════════════════════════════════════════════════════════════════


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="RAG Evaluation Reporter — generate reports from results.json",
    )
    parser.add_argument(
        "--results",
        required=True,
        help="Path to results.json (from runner output)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: same as results.json parent)",
    )
    args = parser.parse_args()

    results_path = Path(args.results).resolve()
    if not results_path.exists():
        logger.error("Results file not found: %s", results_path)
        return

    with open(results_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    out_dir = Path(args.output) if args.output else results_path.parent
    paths = generate_all(data, out_dir)

    print("Generated:")
    for key, path in paths.items():
        print(f"  {key}: {path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    _cli()
