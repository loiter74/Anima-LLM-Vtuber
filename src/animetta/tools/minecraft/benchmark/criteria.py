"""Benchmark success criteria helpers."""

from __future__ import annotations

from typing import Any

from .models import BenchmarkMetrics


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


# ── Voyager 论文对齐指标（mc-bot-voyager-learning T14）─────────────────────────

# 学习期核心技术树节点：木/石/铁/钻石工具 + 基础建造（工作台、熔炉）。
# verified 技能覆盖这些节点 → 直播期可靠产出。
TECH_TREE_KEY_ITEMS: tuple[str, ...] = (
    "wooden_pickaxe",
    "stone_pickaxe",
    "iron_pickaxe",
    "diamond_pickaxe",
    "crafting_table",
    "furnace",
)


def compute_tech_tree_coverage(inventory: dict[str, int]) -> float:
    """计算技术树覆盖率：key 节点在 inventory 中出现的比例（0.0–1.0）。

    Args:
        inventory: {item_name: count}（count > 0 视为已达成）。
    """
    if not TECH_TREE_KEY_ITEMS:
        return 0.0
    have = sum(1 for item in TECH_TREE_KEY_ITEMS if inventory.get(item, 0) > 0)
    return have / len(TECH_TREE_KEY_ITEMS)


def evaluate_voyager_metrics(metrics: BenchmarkMetrics) -> dict[str, Any]:
    """把 BenchmarkMetrics 映射为 Voyager 论文对齐指标摘要。"""
    return {
        "unique_items_discovered": metrics.unique_items_collected,
        "tech_tree_coverage": metrics.tech_tree_coverage,
        "task_success_rate": metrics.task_success_rate,
        "avg_iterations_per_task": metrics.avg_iterations_per_task,
        "total_tokens": metrics.total_tokens,
        "skills_created": metrics.skills_created,
        "skills_reused": metrics.skills_reused,
    }


def _check_voyager_paper_criteria(metrics: BenchmarkMetrics, criteria: dict[str, Any]) -> bool:
    """Voyager 论文指标闸：技术树覆盖 / 平均迭代轮次 / token 消耗。"""
    min_coverage = criteria.get("min_tech_tree_coverage", 0.8)
    max_avg_iters = criteria.get("max_avg_iterations", 4)
    max_tokens = criteria.get("max_total_tokens", 10**9)
    return (
        metrics.tech_tree_coverage >= min_coverage
        and metrics.avg_iterations_per_task <= max_avg_iters
        and metrics.total_tokens <= max_tokens
    )
