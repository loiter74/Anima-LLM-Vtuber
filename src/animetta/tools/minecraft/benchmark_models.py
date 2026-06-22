"""Benchmark data models for Minecraft Voyager evaluations."""

from __future__ import annotations

from dataclasses import dataclass, field
import sys
from enum import Enum

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    class StrEnum(str, Enum):
        """Backport of StrEnum for Python < 3.11."""
        def __str__(self) -> str:
            return self.value
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
    tasks_