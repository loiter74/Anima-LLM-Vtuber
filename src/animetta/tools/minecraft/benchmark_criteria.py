"""Benchmark success criteria helpers."""

from __future__ import annotations

from typing import Any

from .benchmark_models import BenchmarkMetrics


def _l1_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Manhattan distance between two 3D points."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def _count_unique_items(inventory: dict[str, int]) -> int:
    """Count distinct item types with count > 0."""
    return sum(1 for value in inventory.values() if value > 0)


def _check_survival_criteria(
    metrics: BenchmarkMetrics,
    criteria: dict[str, Any],
    inventory: dict[str, int],
) -> bool:
    required: dict[str, int] = criteria.get("required_items", {})
    max_deaths: int = criteria.get("max_deaths", 0)
    if metrics.deaths > max_deaths:
        return False
    return all(inventory.get(item, 0) >= count for item, count in required.items())


def _check_building_criteria(
    metrics: BenchmarkMetrics,
    criteria: dict[str, Any],
    bridge_status: dict[str, Any],
) -> bool:
    min_volume = criteria.get("min_enclosed_volume", 75)
    placed = bridge_status.get("blocks_placed", 0)
    return placed >= min_volume


def _check_learning_criteria(metrics: BenchmarkMetrics, criteria: dict[str, Any]) -> bool:
    min_tasks = criteria.get("min_tasks_completed", 5)
    min_skills = criteria.get("min_skills_learned", 2)
    return metrics.tasks_succeeded >= min_tasks and metrics.skills_created >= min_skills


def _check_tech_tree_criteria(
    metrics: BenchmarkMetrics,
    criteria: dict[str, Any],
    tech_tree_phases_completed: int,
) -> bool:
    min_phases = criteria.get("min_phases_completed", 4)
    max_deaths = criteria.get("max_deaths", 3)
    if metrics.deaths > max_deaths:
        return False
    return tech_tree_phases_completed >= min_phases
