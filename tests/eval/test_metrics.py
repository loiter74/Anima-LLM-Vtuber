"""Unit tests for RAG evaluation metric functions.

Covers all pure metric functions from evaluations/rag/metrics.py
with ≥3 test cases per metric including edge cases.
"""

from __future__ import annotations

import math
import random

import pytest

# Import the module under test
from evaluations.rag.metrics import (
    bootstrap_ci,
    chunk_diversity,
    latency_percentiles,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

# ── Shared Test Data ────────────────────────────────────────────────────

# ChunkId format: (path, start_line, end_line)
A = ("wiki/a.md", 1, 10)
B = ("wiki/b.md", 5, 15)
C = ("wiki/c.md", 20, 30)
D = ("wiki/d.md", 40, 50)
E = ("wiki/e.md", 60, 70)
X = ("wiki/x.md", 100, 110)
Y = ("wiki/y.md", 200, 210)
Z = ("wiki/z.md", 300, 310)

RETRIEVED = [A, B, C, D, E]  # 5 ordered chunks
EXPECTED = [A, C, E]  # 3 ground-truth chunks (positions 0, 2, 4)
DISJOINT = [X, Y, Z]  # no overlap with EXPECTED


# ═══════════════════════════════════════════════════════════════════════════
# recall_at_k
# ═══════════════════════════════════════════════════════════════════════════


class TestRecallAtK:
    """Tests for recall_at_k(retrieved, expected, k)."""

    def test_exact_match_all_retrieved(self):
        """When all expected chunks are in top-k, recall should be 1.0."""
        result = recall_at_k(RETRIEVED, EXPECTED, k=5)
        assert result == pytest.approx(1.0)

    def test_partial_match_some_found(self):
        """When only some expected chunks are in top-k, return fraction."""
        result = recall_at_k(RETRIEVED, EXPECTED, k=2)
        # top-2: [A, B], only A is expected → 1/3
        assert result == pytest.approx(1.0 / 3.0)

    def test_no_match_disjoint(self):
        """When no retrieved chunks match expected, recall is 0.0."""
        result = recall_at_k(DISJOINT, EXPECTED, k=3)
        assert result == 0.0

    def test_empty_expected_returns_zero(self):
        """When expected is empty, recall is 0.0 (avoid division by zero)."""
        result = recall_at_k(RETRIEVED, [], k=5)
        assert result == 0.0

    def test_k_zero_returns_zero(self):
        """When k=0, nothing is considered, so recall is 0.0."""
        result = recall_at_k(RETRIEVED, EXPECTED, k=0)
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# precision_at_k
# ═══════════════════════════════════════════════════════════════════════════


class TestPrecisionAtK:
    """Tests for precision_at_k(retrieved, expected, k)."""

    def test_exact_match_proportion(self):
        """When all top-k are relevant, precision is hits / k."""
        # Only A is expected among top-2 [A, B]
        result = precision_at_k(RETRIEVED, EXPECTED, k=2)
        assert result == pytest.approx(0.5)  # 1 hit / 2

    def test_partial_match(self):
        """Fraction of top-k that are relevant."""
        result = precision_at_k(RETRIEVED, EXPECTED, k=5)
        assert result == pytest.approx(3.0 / 5.0)  # 3 hits / 5

    def test_no_match_disjoint(self):
        """When none of the expected chunks are in retrieved, precision is 0.0."""
        result = precision_at_k(DISJOINT, EXPECTED, k=3)
        assert result == 0.0

    def test_empty_retrieved_returns_zero(self):
        """When retrieved is empty, precision is 0.0."""
        result = precision_at_k([], EXPECTED, k=5)
        assert result == 0.0

    def test_k_larger_than_retrieved(self):
        """When k > len(retrieved), denominator = len(retrieved)."""
        result = precision_at_k(RETRIEVED, EXPECTED, k=100)
        # hits=3, denominator=min(100,5)=5 → 3/5 = 0.6
        assert result == pytest.approx(0.6)


# ═══════════════════════════════════════════════════════════════════════════
# mrr
# ═══════════════════════════════════════════════════════════════════════════


class TestMRR:
    """Tests for mrr(retrieved, expected)."""

    def test_first_position_hit(self):
        """When the first retrieved chunk is relevant, MRR = 1.0."""
        result = mrr(RETRIEVED, EXPECTED)
        assert result == pytest.approx(1.0)  # A is at position 0 → rank 1 → 1/1

    def test_second_position_hit(self):
        """When the second retrieved chunk is the first relevant, MRR = 0.5."""
        retrieved = [X, A, B, C]  # A at position 2 (1-indexed)
        result = mrr(retrieved, EXPECTED)
        assert result == pytest.approx(0.5)

    def test_no_match_returns_zero(self):
        """When no retrieved chunks are in expected, MRR = 0.0."""
        result = mrr(DISJOINT, EXPECTED)
        assert result == 0.0

    def test_empty_expected_returns_zero(self):
        """When expected is empty, MRR = 0.0."""
        result = mrr(RETRIEVED, [])
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# ndcg_at_k
# ═══════════════════════════════════════════════════════════════════════════


class TestNDCGAtK:
    """Tests for ndcg_at_k(retrieved, expected, k)."""

    def test_perfect_ordering(self):
        """When retrieved matches expected in exact order, nDCG = 1.0."""
        # All 3 expected chunks ranked first, in order
        result = ndcg_at_k(EXPECTED, EXPECTED, k=3)
        assert result == pytest.approx(1.0)

    def test_imperfect_ordering(self):
        """When relevant chunks are scattered, nDCG < 1.0."""
        # retrieved = [A, B, C], expected = [A, C, E]
        # DCG@3 = 1/log2(2) + 0 + 1/log2(4) = 1 + 0 + 0.5 = 1.5
        # IDCG@3 = 1/log2(2) + 1/log2(3) + 1/log2(4) ≈ 1 + 0.63093 + 0.5 = 2.13093
        # nDCG ≈ 1.5 / 2.13093 ≈ 0.7039
        result = ndcg_at_k(RETRIEVED, EXPECTED, k=3)
        expected_ndcg = 1.5 / (1.0 / math.log2(2) + 1.0 / math.log2(3) + 1.0 / math.log2(4))
        assert result == pytest.approx(expected_ndcg)

    def test_no_match_returns_zero(self):
        """When no retrieved chunks match expected, nDCG = 0.0."""
        result = ndcg_at_k(DISJOINT, EXPECTED, k=3)
        assert result == 0.0

    def test_empty_expected_returns_zero(self):
        """When expected is empty, IDCG = 0, so nDCG = 0.0."""
        result = ndcg_at_k(RETRIEVED, [], k=3)
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# latency_percentiles
# ═══════════════════════════════════════════════════════════════════════════


class TestLatencyPercentiles:
    """Tests for latency_percentiles(timings_ms)."""

    def test_normal_distribution(self):
        """With a range of values, percentiles should be computed correctly."""
        timings = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        result = latency_percentiles(timings)

        assert result["min"] == 10.0
        assert result["max"] == 100.0
        assert result["mean"] == pytest.approx(55.0)
        assert result["p50"] == pytest.approx(55.0)  # interpolated median
        assert result["p95"] > result["p50"]
        assert result["p99"] >= result["p95"]

    def test_single_value(self):
        """With a single value, all percentiles equal that value."""
        result = latency_percentiles([42.0])

        assert result["p50"] == 42.0
        assert result["p75"] == 42.0
        assert result["p90"] == 42.0
        assert result["p95"] == 42.0
        assert result["p99"] == 42.0
        assert result["mean"] == 42.0
        assert result["min"] == 42.0
        assert result["max"] == 42.0

    def test_empty_list_returns_all_zeros(self):
        """An empty list should return all zeros."""
        result = latency_percentiles([])

        assert result["p50"] == 0.0
        assert result["mean"] == 0.0
        assert result["min"] == 0.0
        assert result["max"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# chunk_diversity
# ═══════════════════════════════════════════════════════════════════════════


class TestChunkDiversity:
    """Tests for chunk_diversity(retrieved_chunks)."""

    def test_all_unique_paths(self):
        """When every chunk comes from a different document, diversity = 1.0."""
        chunks = [
            {"path": "a.md"},
            {"path": "b.md"},
            {"path": "c.md"},
            {"path": "d.md"},
            {"path": "e.md"},
        ]
        result = chunk_diversity(chunks)
        assert result == pytest.approx(1.0)

    def test_all_same_path(self):
        """When all chunks come from the same document, diversity = 1/N."""
        chunks = [
            {"path": "same.md"},
            {"path": "same.md"},
            {"path": "same.md"},
            {"path": "same.md"},
            {"path": "same.md"},
        ]
        result = chunk_diversity(chunks)
        assert result == pytest.approx(1.0 / 5.0)

    def test_empty_list_returns_zero(self):
        """An empty list should return 0.0."""
        result = chunk_diversity([])
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# bootstrap_ci
# ═══════════════════════════════════════════════════════════════════════════


class TestBootstrapCI:
    """Tests for bootstrap_ci(samples, n_bootstrap, ci)."""

    def test_known_distribution(self):
        """Bootstrap CI for [1,2,3,4,5] should have mean=3 and lower ≤ mean ≤ upper."""
        random.seed(42)  # reproducible bootstrap
        mean, lower, upper = bootstrap_ci([1.0, 2.0, 3.0, 4.0, 5.0], n_bootstrap=1000)

        assert mean == pytest.approx(3.0)
        assert lower <= mean <= upper, f"Expected lower({lower}) <= mean({mean}) <= upper({upper})"
        # With 1000 bootstrap samples, the CI should be reasonably tight
        assert upper - lower > 0.0, "CI should have non-zero width for varied data"

    def test_single_value_all_equal(self):
        """When all samples are identical, CI collapses to a single point."""
        mean, lower, upper = bootstrap_ci([7.0, 7.0, 7.0, 7.0, 7.0], n_bootstrap=500)

        assert mean == 7.0
        assert lower == 7.0
        assert upper == 7.0


# ═══════════════════════════════════════════════════════════════════════════
# Edge Cases (cross-metric)
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge case tests that apply across multiple metrics."""

    def test_large_k_exceeds_retrieved_length(self):
        """When k is much larger than the retrieved list, metrics should not crash."""
        result_recall = recall_at_k(RETRIEVED, EXPECTED, k=9999)
        result_precision = precision_at_k(RETRIEVED, EXPECTED, k=9999)
        result_ndcg = ndcg_at_k(RETRIEVED, EXPECTED, k=9999)

        # recall = 3/3 = 1.0 (all expected found)
        assert result_recall == pytest.approx(1.0)
        # precision = 3/5 = 0.6 (denominator capped at len(retrieved))
        assert result_precision == pytest.approx(0.6)
        # nDCG should be valid
        assert 0.0 <= result_ndcg <= 1.0

    def test_duplicate_chunks_in_retrieved(self):
        """Duplicate chunks in retrieved are deduplicated by set intersection."""
        dup_retrieved = [A, A, B, C, A]  # A appears 3 times
        expected = [A, C]

        result_recall = recall_at_k(dup_retrieved, expected, k=5)
        result_precision = precision_at_k(dup_retrieved, expected, k=5)

        # Set intersection deduplicates: {A,B,C} ∩ {A,C} = {A,C}, size=2
        assert result_recall == pytest.approx(1.0)  # 2 unique / 2 expected
        assert result_precision == pytest.approx(0.4)  # 2 unique / 5 retrieved
