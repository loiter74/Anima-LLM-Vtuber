"""Pure evaluation metric functions for RAG retrieval quality.

All functions are synchronous and deterministic (except bootstrap_ci which
uses random resampling). No external dependencies beyond stdlib.
"""

from __future__ import annotations

import math
import random
from typing import Any

# ── Type Aliases ───────────────────────────────────────────────────────

ChunkId = tuple[str, int, int]
"""A chunk identifier: (path, start_line, end_line)."""


# ── Helper ──────────────────────────────────────────────────────────────


def _intersect_count(retrieved: list[ChunkId], expected: list[ChunkId], k: int) -> int:
    """Count unique expected chunks found in the first k retrieved chunks.

    Uses set intersection (∩) per the mathematical definition,
    which deduplicates both sides.
    """
    top_k_set = set(retrieved[:k])
    expected_set = set(expected)
    return len(top_k_set & expected_set)


# ── Retrieval Quality Metrics ───────────────────────────────────────────


def recall_at_k(retrieved: list[ChunkId], expected: list[ChunkId], k: int) -> float:
    """|retrieved[:k] ∩ expected| / |expected|.

    Returns 0.0 if expected is empty.
    """
    if not expected:
        return 0.0
    if k <= 0:
        return 0.0
    hits = _intersect_count(retrieved, expected, k)
    return hits / len(expected)


def precision_at_k(retrieved: list[ChunkId], expected: list[ChunkId], k: int) -> float:
    """|retrieved[:k] ∩ expected| / min(k, |retrieved|).

    Returns 0.0 if retrieved is empty.
    """
    if not retrieved:
        return 0.0
    if k <= 0:
        return 0.0
    hits = _intersect_count(retrieved, expected, k)
    denominator = min(k, len(retrieved))
    return hits / denominator


def mrr(retrieved: list[ChunkId], expected: list[ChunkId]) -> float:
    """Mean Reciprocal Rank: 1 / rank of first hit.

    Rank is 1-based. Returns 0.0 if no expected chunks are found,
    or if expected is empty.
    """
    if not expected:
        return 0.0
    expected_set = set(expected)
    for i, chunk in enumerate(retrieved):
        if chunk in expected_set:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(retrieved: list[ChunkId], expected: list[ChunkId], k: int) -> float:
    """Normalized Discounted Cumulative Gain at k.

    Relevance = 1 if chunk in expected, 0 otherwise.
    DCG_k = Σ rel_i / log2(i + 1)   (i is 1-based position)
    IDCG_k = ideal DCG (all relevant ranked first).
    Returns 0.0 if IDCG is 0 or k <= 0.
    """
    if k <= 0:
        return 0.0

    expected_set = set(expected)

    # DCG: discount at position i (1-indexed) = 1 / log2(i+1)
    dcg = 0.0
    for i, chunk in enumerate(retrieved[:k]):
        rel = 1.0 if chunk in expected_set else 0.0
        if rel > 0:
            dcg += rel / math.log2((i + 1) + 1)  # i+1 → position, +1 for log2(pos+1)

    # IDCG: ideal ordering — all relevant first, then irrelevant
    num_relevant = len(expected)
    idcg = 0.0
    for i in range(min(num_relevant, k)):
        idcg += 1.0 / math.log2((i + 1) + 1)

    if idcg == 0.0:
        return 0.0

    return dcg / idcg


# ── Performance Metrics ─────────────────────────────────────────────────


def latency_percentiles(timings_ms: list[float]) -> dict[str, float]:
    """Compute latency percentiles from a list of timing values.

    Returns:
        dict with keys: p50, p75, p90, p95, p99, mean, min, max.
        All values are 0.0 for an empty list.
    """
    if not timings_ms:
        return {
            "p50": 0.0,
            "p75": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "mean": 0.0,
            "min": 0.0,
            "max": 0.0,
        }

    sorted_data = sorted(timings_ms)
    n = len(sorted_data)

    def _percentile(p: float) -> float:
        """Linear interpolation percentile (0–100)."""
        rank = p / 100.0 * (n - 1)
        lower = int(rank)
        upper = lower + 1
        if upper >= n:
            return sorted_data[-1]
        weight = rank - lower
        return sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight

    return {
        "p50": _percentile(50),
        "p75": _percentile(75),
        "p90": _percentile(90),
        "p95": _percentile(95),
        "p99": _percentile(99),
        "mean": sum(sorted_data) / n,
        "min": sorted_data[0],
        "max": sorted_data[-1],
    }


# ── Diversity Metrics ───────────────────────────────────────────────────


def chunk_diversity(retrieved_chunks: list[dict[str, Any]]) -> float:
    """Fraction of distinct source documents among retrieved chunks.

    Each chunk dict must have a 'path' key.
    Returns 0.0 if the list is empty.
    """
    if not retrieved_chunks:
        return 0.0
    unique_paths = {chunk["path"] for chunk in retrieved_chunks}
    return len(unique_paths) / len(retrieved_chunks)


# ── Statistical Tools ───────────────────────────────────────────────────


def bootstrap_ci(
    samples: list[float],
    n_bootstrap: int = 1000,
    ci: float = 0.95,
) -> tuple[float, float, float]:
    """Bootstrap confidence interval for the mean.

    Resamples with replacement n_bootstrap times, computes the mean of each
    resample, then returns (mean_of_means, lower_bound, upper_bound) based
    on percentiles.

    Args:
        samples: Observed sample values.
        n_bootstrap: Number of bootstrap resamples.
        ci: Confidence level (e.g. 0.95 for 95% CI).

    Returns:
        (mean, lower_bound, upper_bound).
    """
    if not samples:
        return (0.0, 0.0, 0.0)

    means: list[float] = []
    for _ in range(n_bootstrap):
        resample = random.choices(samples, k=len(samples))
        means.append(sum(resample) / len(resample))

    means.sort()

    tail = (1.0 - ci) / 2.0
    lower_idx = int(tail * n_bootstrap)
    upper_idx = int((1.0 - tail) * n_bootstrap) - 1
    # Clamp to valid range
    lower_idx = max(0, lower_idx)
    upper_idx = min(n_bootstrap - 1, upper_idx)

    overall_mean = sum(samples) / len(samples)
    return (overall_mean, means[lower_idx], means[upper_idx])
