"""Hermetic demo of the bounded typed fallback workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from animetta.tools.minecraft.survival.workflows import iron_survival_workflow


@dataclass(frozen=True)
class DemoStep:
    capability: str
    parameters: dict[str, Any]
    success: bool
    recovered: bool = False
    error_code: str = ""


@dataclass(frozen=True)
class DemoReport:
    completed: bool
    steps: tuple[DemoStep, ...]
    final_inventory: dict[str, int]

    def summary(self) -> dict[str, Any]:
        return {
            "completed": self.completed,
            "steps": len(self.steps),
            "recoveries_triggered": count_recoveries(self.steps),
            "final_inventory": self.final_inventory,
        }


@dataclass
class ScriptedCapabilityRuntime:
    """In-memory capability fixture; it is not a bridge or production owner."""

    inventory: dict[str, int] = field(default_factory=dict)
    failures: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def inject_failure(self, capability: str, key: str, code: str) -> None:
        self.failures.setdefault((capability, key), []).append(code)

    @staticmethod
    def _key(capability: str, parameters: dict[str, Any]) -> str:
        names = {"collect": "block_type", "craft": "recipe", "smelt": "item"}
        return str(parameters.get(names[capability], ""))

    async def execute(self, capability: str, parameters: dict[str, Any]) -> str | None:
        key = self._key(capability, parameters)
        queued = self.failures.get((capability, key), [])
        if queued:
            return queued.pop(0)
        count = int(parameters.get("count", 1))
        if capability == "collect":
            yielded = {
                "stone": "cobblestone",
                "coal_ore": "coal",
                "iron_ore": "raw_iron",
            }.get(key, key)
            self.inventory[yielded] = self.inventory.get(yielded, 0) + count
        elif capability == "craft":
            self.inventory[key] = self.inventory.get(key, 0) + count
        elif capability == "smelt" and key == "raw_iron":
            self.inventory["iron_ingot"] = self.inventory.get("iron_ingot", 0) + count
        return None


def build_demo_scenario() -> ScriptedCapabilityRuntime:
    runtime = ScriptedCapabilityRuntime()
    runtime.inject_failure("collect", "oak_log", "PARTIAL_COLLECT")
    runtime.inject_failure("craft", "wooden_pickaxe", "NO_CRAFTING_TABLE")
    runtime.inject_failure("smelt", "raw_iron", "SMELT_NO_FURNACE")
    return runtime


async def run_demo_workflow(runtime: ScriptedCapabilityRuntime) -> DemoReport:
    traces: list[DemoStep] = []
    for step in iron_survival_workflow().steps:
        code = await runtime.execute(step.capability, step.parameters)
        recovered = code is not None
        if recovered:
            second = await runtime.execute(step.capability, step.parameters)
            if second is not None:
                traces.append(DemoStep(step.capability, step.parameters, False, True, second))
                return DemoReport(False, tuple(traces), dict(runtime.inventory))
        traces.append(DemoStep(step.capability, step.parameters, True, recovered, code or ""))
    return DemoReport(
        runtime.inventory.get("iron_ingot", 0) >= 1,
        tuple(traces),
        dict(runtime.inventory),
    )


def build_phase_traces(report: DemoReport) -> list[DemoStep]:
    return list(report.steps)


def count_recoveries(traces: list[DemoStep] | tuple[DemoStep, ...]) -> int:
    return sum(step.recovered for step in traces)
