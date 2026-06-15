from __future__ import annotations

"""Eval-specific fixtures for RAG evaluation tests.

Fixtures here are reusable across test modules in tests/eval/.
Metrics tests (test_metrics.py) are pure functions and don't require fixtures,
but these are provided for future integration tests.
"""

import pytest

# Type alias matching evaluations/rag/metrics.py
ChunkId = tuple[str, int, int]


@pytest.fixture
def sample_retrieved() -> list[ChunkId]:
    """Simulated search results: list of (path, start_line, end_line)."""
    return [
        ("wiki/entities/cat.md", 1, 5),
        ("wiki/entities/dog.md", 10, 15),
        ("wiki/entities/bird.md", 20, 25),
        ("wiki/entities/fish.md", 30, 35),
        ("wiki/entities/hamster.md", 40, 45),
    ]


@pytest.fixture
def sample_expected() -> list[ChunkId]:
    """Ground truth: list of (path, start_line, end_line)."""
    return [
        ("wiki/entities/cat.md", 1, 5),
        ("wiki/entities/bird.md", 20, 25),
        ("wiki/entities/hamster.md", 40, 45),
    ]


@pytest.fixture
def sample_timings() -> list[float]:
    """Sample latency values in milliseconds."""
    return [12.5, 15.0, 10.0, 18.2, 14.1, 11.8, 13.3, 100.0, 9.5, 16.7]


@pytest.fixture
def sample_chunks() -> list[dict]:
    """Sample retrieved chunks as dicts with 'path' key for diversity testing."""
    return [
        {"path": "wiki/entities/cat.md", "score": 0.95},
        {"path": "wiki/entities/cat.md", "score": 0.87},
        {"path": "wiki/entities/dog.md", "score": 0.82},
        {"path": "wiki/entities/bird.md", "score": 0.78},
        {"path": "wiki/entities/cat.md", "score": 0.71},
    ]
