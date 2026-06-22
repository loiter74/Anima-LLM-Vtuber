"""Compatibility facade for Minecraft benchmark APIs."""

from __future__ import annotations

from ..autonomous.loop import AutonomousLoop
from .criteria import (
    _check_building_criteria,
    _check_learning_criteria,
    _check_survival_criteria,
    _check_tech_tree_criteria,
    _count_unique_items,
    _l1_distance,
)
from .models import (
    BenchmarkConfig,
    BenchmarkMetrics,
    BenchmarkMode,
    BenchmarkScenario,
    _Snapshot,
)
from .report import generate_benchmark_report
from .runner import BenchmarkRunner
from .scenarios import (
    ALL_CONFIGS,
    ALL_SCENARIOS,
    BUILDING_CHALLENGE,
    LEARNING_CHALLENGE,
    SURVIVAL_CHALLENGE,
    TECH_TREE_UNLOCK,
)

__all__ = [
    "BenchmarkMode",
    "BenchmarkConfig",
    "BenchmarkScenario",
    "BenchmarkMetrics",
    "_Snapshot",
    "SURVIVAL_CHALLENGE",
    "BUILDING_CHALLENGE",
    "LEARNING_CHALLENGE",
    "TECH_TREE_UNLOCK",
    "ALL_SCENARIOS",
    "ALL_CONFIGS",
    "_l1_distance",
    "_count_unique_items",
    "_check_survival_criteria",
    "_check_building_criteria",
    "_check_learning_criteria",
    "_check_tech_tree_criteria",
    "generate_benchmark_report",
    "AutonomousLoop",
    "BenchmarkRunner",
]
