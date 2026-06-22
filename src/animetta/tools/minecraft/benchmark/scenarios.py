"""Benchmark scenario definitions for Minecraft Voyager evaluations."""

from __future__ import annotations

from .models import BenchmarkConfig, BenchmarkMode, BenchmarkScenario

SURVIVAL_CHALLENGE = BenchmarkScenario(
    name="Survival Challenge",
    description=(
        "Collect iron_pickaxe + iron_sword and survive without dying. "
        "Tests resource gathering, crafting, and threat avoidance."
    ),
    success_criteria={"required_items": {"iron_pickaxe": 1, "iron_sword": 1}, "max_deaths": 0},
    time_limit_minutes=20,
)

BUILDING_CHALLENGE = BenchmarkScenario(
    name="Building Challenge",
    description=(
        "Build an enclosed space of at least 5x5x3 blocks. "
        "Tests material gathering, planning, and block placement."
    ),
    success_criteria={"min_enclosed_volume": 75, "min_dimensions": (5, 5, 3)},
    time_limit_minutes=25,
)

LEARNING_CHALLENGE = BenchmarkScenario(
    name="Learning Challenge",
    description=(
        "Complete 5 distinct tasks and verify skill accumulation. "
        "Tests the skill extraction and reuse pipeline."
    ),
    success_criteria={"min_tasks_completed": 5, "min_skills_learned": 2},
    time_limit_minutes=15,
)

TECH_TREE_UNLOCK = BenchmarkScenario(
    name="Tech Tree Unlock",
    description=(
        "Progress through the full tech tree (wood -> stone -> iron -> diamond). "
        "Tests phase-based progression, skill search/execution/reuse, and milestone tracking."
    ),
    success_criteria={"min_phases_completed": 4, "max_deaths": 3},
    time_limit_minutes=60,
)

ALL_SCENARIOS: list[BenchmarkScenario] = [
    SURVIVAL_CHALLENGE,
    BUILDING_CHALLENGE,
    LEARNING_CHALLENGE,
    TECH_TREE_UNLOCK,
]

ALL_CONFIGS: list[BenchmarkConfig] = [
    BenchmarkConfig(name="Rule-Only", mode=BenchmarkMode.RULE_ONLY),
    BenchmarkConfig(name="LLM-Only", mode=BenchmarkMode.LLM_ONLY),
    BenchmarkConfig(name="Predefined Skills", mode=BenchmarkMode.PREDEFINED),
    BenchmarkConfig(name="Full Voyager", mode=BenchmarkMode.FULL_VOYAGER),
]
