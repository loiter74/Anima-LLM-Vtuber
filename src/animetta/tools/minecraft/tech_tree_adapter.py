"""Adapters from tech-tree reports to benchmark metrics."""

from __future__ import annotations

from loguru import logger

from .benchmark_models import BenchmarkMetrics
from .tech_tree_models import TechTreeReport


def report_to_benchmark_metrics(report: TechTreeReport) -> BenchmarkMetrics:
    """Convert tech tree metrics to generic benchmark metrics."""
    metrics = report.metrics
    total_phases = len(report.config.phases)
    completed = len(metrics.phases_completed) >= total_phases
    unique_items = sum(1 for count in metrics.items_collected.values() if count > 0)

    benchmark = BenchmarkMetrics(
        time_to_milestone=metrics.total_time_seconds if completed else 0.0,
        unique_items_collected=unique_items,
        skills_created=metrics.skills_learned,
        skills_reused=metrics.skills_reused,
        deaths=metrics.deaths,
        final_inventory=dict(metrics.items_collected),
        completed=completed,
        elapsed_seconds=metrics.total_time_seconds,
    )
    logger.info(
        f"[TechTreeRunner] Converted to BenchmarkMetrics: completed={completed}, "
        f"items={unique_items}, skills={metrics.skills_learned}+{metrics.skills_reused}"
    )
    return benchmark
