"""Compatibility facade for Minecraft tech-tree APIs."""

from __future__ import annotations

from .adapter import report_to_benchmark_metrics
from .defaults import (
    _PREDEFINED_PHASES,
    DIAMOND_PHASE,
    IRON_PHASE,
    STONE_PHASE,
    WOOD_PHASE,
    _phase_tasks,
    create_default_tech_tree,
)
from .models import TechTreeConfig, TechTreeMetrics, TechTreePhase, TechTreeReport
from .report import _REPORT_DIR, render_markdown_report, save_markdown_report

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
]
