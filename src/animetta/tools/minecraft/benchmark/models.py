"""Benchmark data models for Minecraft Voyager evaluations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class BenchmarkMode(StrEnum):
    """Configuration modes for benchmark runs."""

    RULE_ONLY = "rule-only"
    LLM_ONLY = "llm-only"
    PREDEFINED = "predefined"
    FULL_VOYAGER = "full-voyager"


@dataclass
class BenchmarkConfig:
    """Configuration for a single benchmark run."""

    name: str
    mode: BenchmarkMode
    world_seed: str | None = None
    time_limit_minutes: int = 20


@dataclass
class BenchmarkScenario:
    """A benchmark scenario with success criteria."""

    name: str
    description: str
    success_criteria: dict[str, Any]
    time_limit_minutes: int


@dataclass
class BenchmarkMetrics:
    """Collected metrics from a single benchmark run."""

    time_to_milestone: float = 0.0
    unique_items_collected: int = 0
    distance_traveled: float = 0.0
    skills_created: int = 0
    skills_reused: int = 0
    task_success_rate: float = 0.0
    deaths: int = 0
    final_inventory: dict[str, int] = field(default_factory=dict)
    completed: bool = False
    elapsed_seconds: float = 0.0
    tasks_attempted: int = 0
    tasks_succeeded: int = 0
    # ── Voyager 论文对齐指标（mc-bot-voyager-learning T14）───────────────────
    # 技术树覆盖率（0.0–1.0）：木/石/铁/钻石工具 + 基础建造 key 节点达成比例
    tech_tree_coverage: float = 0.0
    # 单任务平均迭代轮次（code_generator ≤4 轮）：越低越好
    avg_iterations_per_task: float = 0.0
    # 学习期累计 token 消耗（云 LLM 成本）
    total_tokens: int = 0


@dataclass
class _Snapshot:
    """Internal periodic world-state sample."""

    timestamp: float
    x: float
    y: float
    z: float
    health: float
    food: float
    inventory: dict[str, int]
