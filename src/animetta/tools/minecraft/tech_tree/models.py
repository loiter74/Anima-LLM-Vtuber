"""Data models for Minecraft tech-tree progression."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_PREDEFINED_PHASE_COUNT = 4


@dataclass
class TechTreePhase:
    name: str
    time_budget_minutes: int
    required_items: dict[str, int]
    skills_to_learn: list[str]
    description: str

    @property
    def time_budget_seconds(self) -> float:
        return self.time_budget_minutes * 60.0

    def is_complete(self, inventory: dict[str, int]) -> bool:
        return all(
            inventory.get(item, 0) >= needed
            for item, needed in self.required_items.items()
        )

    def missing_items(self, inventory: dict[str, int]) -> dict[str, int]:
        missing: dict[str, int] = {}
        for item, needed in self.required_items.items():
            have = inventory.get(item, 0)
            if have < needed:
                missing[item] = needed - have
        return missing


@dataclass
class TechTreeConfig:
    phases: list[TechTreePhase]
    total_time_budget_minutes: int = 60

    @property
    def total_time_budget_seconds(self) -> float:
        return self.total_time_budget_minutes * 60.0

    def get_phase(self, name: str) -> TechTreePhase | None:
        for phase in self.phases:
            if phase.name == name:
                return phase
        return None

    def next_phase(self, current_name: str) -> TechTreePhase | None:
        for i, phase in enumerate(self.phases):
            if phase.name == current_name and i + 1 < len(self.phases):
                return self.phases[i + 1]
        return None

    def validate(self) -> list[str]:
        warnings: list[str] = []
        if not self.phases:
            warnings.append("TechTreeConfig has no phases defined")
            return warnings
        phase_total = sum(p.time_budget_minutes for p in self.phases)
        if phase_total > self.total_time_budget_minutes * 1.5:
            warnings.append(
                f"Sum of phase budgets ({phase_total}min) significantly exceeds "
                + f"total_time_budget ({self.total_time_budget_minutes}min)"
            )
        names = [p.name for p in self.phases]
        dupes = {name for name in names if names.count(name) > 1}
        if dupes:
            warnings.append(f"Duplicate phase names: {sorted(dupes)}")
        for phase in self.phases:
            if not phase.required_items:
                warnings.append(f"Phase '{phase.name}' has no required_items")
        return warnings


@dataclass
class TechTreeMetrics:
    phases_completed: list[str] = field(default_factory=list)
    total_time_seconds: float = 0.0
    items_collected: dict[str, int] = field(default_factory=dict)
    skills_learned: int = 0
    skills_reused: int = 0
    deaths: int = 0

    @property
    def completion_rate(self) -> float:
        if not _PREDEFINED_PHASE_COUNT:
            return 0.0
        return len(self.phases_completed) / _PREDEFINED_PHASE_COUNT

    @property
    def total_skills_used(self) -> int:
        return self.skills_learned + self.skills_reused

    def summary(self) -> str:
        return (
            f"Phases: {len(self.phases_completed)}/{_PREDEFINED_PHASE_COUNT} | "
            f"Time: {self.total_time_seconds:.0f}s | "
            f"Skills: {self.skills_learned}L/{self.skills_reused}R | "
            f"Deaths: {self.deaths}"
        )


@dataclass
class TechTreeReport:
    config: TechTreeConfig
    metrics: TechTreeMetrics
    phase_details: list[dict[str, Any]] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
