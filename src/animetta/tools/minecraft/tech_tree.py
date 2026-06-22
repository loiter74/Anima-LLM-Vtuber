"""Compatibility facade for Minecraft tech-tree APIs."""

from __future__ import annotations

from .tech_tree_adapter import report_to_benchmark_metrics
from .tech_tree_defaults import (
    _PREDEFINED_PHASES,
    DIAMOND_PHASE,
    IRON_PHASE,
    STONE_PHASE,
    WOOD_PHASE,
    _phase_tasks,
    create_default_tech_tree,
)
from .tech_tree_models import TechTreeConfig, TechTreeMetrics, TechTreePhase, TechTreeReport
from .tech_tree_report import _REPORT_DIR, render_markdown_report, save_markdown_report
from .tech_tree_runner import TechTreeRunner

__all__ = [
    "TechTreePhase",
    "TechTreeConfig",
    "TechTreeMetrics",
    "TechTreeReport",
    "WOOD_PHASE",
    "STONE_PHASE",
    "IRON_PHASE",
    "DIAMOND_PHASE",
    "_PREDEFINED_PHASES",
    "create_default_tech_tree",
    "_REPORT_DIR",
    "_phase_tasks",
    "render_markdown_report",
    "save_markdown_report",
    "report_to_benchmark_metrics",
    "TechTreeRunner",
]
