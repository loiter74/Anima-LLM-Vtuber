"""Execution runner for Minecraft tech-tree progression."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from ..benchmark.models import BenchmarkMetrics
from .adapter import report_to_benchmark_metrics
from .defaults import _phase_tasks, create_default_tech_tree
from .models import TechTreeConfig, TechTreeMetrics, TechTreePhase, TechTreeReport
from .report import render_markdown_report, save_markdown_report

if TYPE_CHECKING:
    from ..core.bridge import MinecraftBridge
    from ..skill.library import SkillLibrary


class TechTreeRunner:
    """Execute a full tech-tree run and collect progression metrics."""

    def __init__(
        self,
        bridge: MinecraftBridge,
        skill_library: SkillLibrary,
        config: TechTreeConfig | None = None,
    ) -> None:
        self._bridge = bridge
        self._skill_library = skill_library
        self._config = config or create_default_tech_tree()
        self._metrics = TechTreeMetrics()
        self._phase_details: list[dict[str, Any]] = []
        self._run_start: float = 0.0
        self._deaths_at_start: int = 0
        logger.info(
            f"[TechTreeRunner] Initialized: {len(self._config.phases)} phases, "
            f"{self._config.total_time_budget_minutes}min total budget"
        )

    async def run(self) -> TechTreeMetrics:
        self._run_start = time.monotonic()
        self._metrics = TechTreeMetrics()
        self._phase_details = []
        self._deaths_at_start = await self._get_death_count()
        logger.info("[TechTreeRunner] Starting tech tree run")
        for phase in self._config.phases:
            elapsed = time.monotonic() - self._run_start
            if elapsed >= self._config.total_time_budget_seconds:
                logger.warning(
                    f"[TechTreeRunner] Global time budget exhausted ({elapsed:.0f}s / "
                    f"{self._config.total_time_budget_seconds:.0f}s) - "
                    f"stopping before phase '{phase.name}'"
                )
                break
            completed = await self._run_phase(phase)
            if completed:
                self._metrics.phases_completed.append(phase.name)
                logger.info(f"[TechTreeRunner] Phase '{phase.name}' completed")
            else:
                logger.warning(f"[TechTreeRunner] Phase '{phase.name}' failed or timed out")
        self._metrics.total_time_seconds = time.monotonic() - self._run_start
        self._metrics.items_collected = await self._get_inventory()
        self._metrics.deaths = max(0, await self._get_death_count() - self._deaths_at_start)
        logger.info(f"[TechTreeRunner] Run finished - {self._metrics.summary()}")
        return self._metrics

    async def _run_phase(self, phase: TechTreePhase) -> bool:
        phase_start = time.monotonic()
        budget = phase.time_budget_seconds
        tasks = _phase_tasks(phase.name)
        logger.info(
            f"[TechTreeRunner] Phase '{phase.name}' - "
            f"{len(tasks)} tasks, {phase.time_budget_minutes}min budget"
        )
        for task_label, action, params in tasks:
            elapsed = time.monotonic() - phase_start
            if elapsed >= budget:
                logger.warning(
                    f"[TechTreeRunner] Phase '{phase.name}' timed out "
                    f"({elapsed:.0f}s / {budget:.0f}s) at task '{task_label}'"
                )
                self._record_phase_detail(phase, phase_start, completed=False)
                return False
            _ = await self._execute_task(task_label, action, params)
            inventory = await self._get_inventory()
            if await self._check_milestone(phase, inventory):
                logger.info(
                    f"[TechTreeRunner] Phase '{phase.name}' milestone reached after task '{task_label}'"
                )
                self._record_phase_detail(phase, phase_start, completed=True)
                return True
        inventory = await self._get_inventory()
        completed = await self._check_milestone(phase, inventory)
        self._record_phase_detail(phase, phase_start, completed=completed)
        if not completed:
            logger.warning(
                f"[TechTreeRunner] Phase '{phase.name}' - all tasks exhausted "
                f"but milestone not achieved (missing: {phase.missing_items(inventory)})"
            )
        return completed

    def _record_phase_detail(self, phase: TechTreePhase, phase_start: float, completed: bool) -> None:
        self._phase_details.append(
            {
                "name": phase.name,
                "completed": completed,
                "elapsed_seconds": time.monotonic() - phase_start,
                "items_collected": dict(self._metrics.items_collected),
                "missing_items": {},
            }
        )

    async def _check_milestone(self, phase: TechTreePhase, inventory: dict[str, int]) -> bool:
        return phase.is_complete(inventory)

    async def _execute_task(self, task_label: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        skill = await self._find_skill(task_label)
        if skill is not None:
            logger.info(f"[TechTreeRunner] Task '{task_label}' - using skill '{skill.id}'")
            context = await self._build_context()
            result = await self._skill_library.execute_skill_by_id(skill.id, self._bridge, context)
            if result.success:
                await self._skill_library.update_success(skill.id)
                self._metrics.skills_reused += 1
                logger.info(f"[TechTreeRunner] Skill '{skill.id}' succeeded ({result.duration:.1f}s)")
                return {"status": "success", "result": result.context_updates}
            await self._skill_library.update_failure(skill.id)
            logger.warning(
                f"[TechTreeRunner] Skill '{skill.id}' failed: {result.reason} - falling back to bridge command"
            )
        logger.info(f"[TechTreeRunner] Task '{task_label}' - bridge {action}({params})")
        timeout = 120.0 if action in ("collect", "mine") else 60.0
        resp = await self._bridge.send_command(action, params, timeout=timeout)
        if resp.get("status") != "success":
            logger.warning(f"[TechTreeRunner] Task '{task_label}' failed: {resp.get('result', 'unknown')}")
        return resp

    async def _find_skill(self, task_label: str) -> Any | None:
        matches = await self._skill_library.search_by_keyword(task_label, limit=1)
        if matches:
            return matches[0]
        goal = task_label.replace("_", " ")
        matches = await self._skill_library.search_skills(goal, limit=1)
        if matches:
            return matches[0]
        return None

    async def _build_context(self) -> dict[str, Any]:
        try:
            resp = await self._bridge.send_command("status", timeout=5.0)
            if resp.get("status") == "success":
                result = resp.get("result", {})
                if isinstance(result, dict):
                    return {
                        "health": result.get("health", 20),
                        "food": result.get("food", 20),
                        "is_day": result.get("is_day", True),
                        "is_night": result.get("is_night", False),
                        "inventory": result.get("inventory", {}),
                    }
        except Exception:
            pass
        return {}

    async def _get_inventory(self) -> dict[str, int]:
        try:
            resp = await self._bridge.send_command("status", timeout=5.0)
            if resp.get("status") == "success":
                result = resp.get("result", {})
                if isinstance(result, dict):
                    return result.get("inventory", {})
        except Exception:
            logger.debug("[TechTreeRunner] Could not fetch inventory")
        return {}

    async def _get_death_count(self) -> int:
        try:
            resp = await self._bridge.send_command("status", timeout=5.0)
            if resp.get("status") == "success":
                result = resp.get("result", {})
                if isinstance(result, dict):
                    return int(result.get("deaths", 0))
        except Exception:
            logger.debug("[TechTreeRunner] Could not fetch death count")
        return 0

    def generate_report(self) -> TechTreeReport:
        report = TechTreeReport(
            config=self._config,
            metrics=self._metrics,
            phase_details=list(self._phase_details),
        )
        logger.info(
            f"[TechTreeRunner] Generated report: {len(report.metrics.phases_completed)}/"
            f"{len(self._config.phases)} phases, {report.metrics.total_time_seconds:.1f}s elapsed"
        )
        return report

    def generate_markdown_report(self, report: TechTreeReport | None = None) -> str:
        if report is None:
            report = self.generate_report()
        return render_markdown_report(report)

    def save_report(self, report: TechTreeReport | None = None, directory: Path | str | None = None) -> Path:
        if report is None:
            report = self.generate_report()
        markdown = self.generate_markdown_report(report)
        return save_markdown_report(report, markdown, directory)

    def generate_benchmark_metrics(self, report: TechTreeReport | None = None) -> BenchmarkMetrics:
        if report is None:
            report = self.generate_report()
        return report_to_benchmark_metrics(report)
