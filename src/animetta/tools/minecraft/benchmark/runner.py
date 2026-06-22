"""Benchmark runner for Minecraft Voyager configurations."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

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
from .scenarios import ALL_CONFIGS, ALL_SCENARIOS
from ..skill.library import Skill, SkillLibrary

if TYPE_CHECKING:
    from ..core.bridge import MinecraftBridge
    from .loop.rules_engine import RulesEngine


class BenchmarkRunner:
    """Runs MC Bot through benchmark scenarios with different configurations."""

    _SNAPSHOT_INTERVAL: float = 5.0

    def __init__(
        self,
        bridge: MinecraftBridge,
        llm_service: Any | None = None,
        skill_library: SkillLibrary | None = None,
        rules_engine: RulesEngine | None = None,
    ):
        self._bridge = bridge
        self._llm_service = llm_service
        self._skill_library = skill_library or SkillLibrary()
        self._rules_engine = rules_engine
        self._predefined_skills: list[Skill] = []
        logger.info("[BenchmarkRunner] Initialized")

    async def load_predefined_skills(self) -> None:
        try:
            from ..skill.predefined import get_predefined_skills

            self._predefined_skills = get_predefined_skills()
            logger.info(f"[BenchmarkRunner] Loaded {len(self._predefined_skills)} predefined skills")
        except ImportError:
            logger.warning(
                "[BenchmarkRunner] predefined_skills module not found, predefined mode will use empty skill set"
            )

    async def run_scenario(self, scenario: BenchmarkScenario, config: BenchmarkConfig) -> BenchmarkMetrics:
        logger.info(
            f"[BenchmarkRunner] Starting '{scenario.name}' with mode '{config.mode.value}' "
            f"(limit={config.time_limit_minutes}min, seed={config.world_seed})"
        )
        run_library = SkillLibrary()
        if config.mode == BenchmarkMode.PREDEFINED:
            for skill in self._predefined_skills:
                await run_library.save_skill(skill)
        elif config.mode == BenchmarkMode.FULL_VOYAGER:
            for skill in await self._skill_library.get_all_skills():
                await run_library.save_skill(skill)

        planner = self._llm_service if config.mode in (BenchmarkMode.LLM_ONLY, BenchmarkMode.FULL_VOYAGER) else None
        skill_extractor = None
        skill_validator = None
        if config.mode == BenchmarkMode.FULL_VOYAGER:
            try:
                from ..skill.extractor import SkillExtractor
                from ..skill.validator import SkillValidator

                skill_extractor = SkillExtractor()
                skill_validator = SkillValidator()
            except ImportError:
                logger.warning("[BenchmarkRunner] SkillExtractor/SkillValidator not available")

        loop = AutonomousLoop(
            bridge=self._bridge,
            rules=self._rules_engine,
            skill_library=run_library if config.mode != BenchmarkMode.RULE_ONLY else None,
            planner=planner,
            config={"mode": config.mode.value},
            skill_extractor=skill_extractor,
            skill_validator=skill_validator,
        )

        snapshots: list[_Snapshot] = []
        start_skills = len(await run_library.get_all_skills())
        start_learned = len(await run_library.get_learned_skills())
        deaths = 0
        tasks_attempted = 0
        tasks_succeeded = 0

        if config.world_seed:
            try:
                await self._bridge.send_command("chat", {"message": f"/seed {config.world_seed}"}, timeout=10.0)
            except Exception:
                logger.debug("[BenchmarkRunner] Could not set world seed")

        async def _collect_snapshots() -> None:
            nonlocal deaths
            while True:
                await asyncio.sleep(self._SNAPSHOT_INTERVAL)
                try:
                    status = await self._bridge.send_command("status", timeout=10.0)
                    result = status.get("result", {})
                    if isinstance(result, dict):
                        snap = _Snapshot(
                            timestamp=time.monotonic(),
                            x=float(result.get("x", 0)),
                            y=float(result.get("y", 0)),
                            z=float(result.get("z", 0)),
                            health=float(result.get("health", 20)),
                            food=float(result.get("food", 20)),
                            inventory=dict(result.get("inventory", {})),
                        )
                        snapshots.append(snap)
                        if snap.health <= 0:
                            deaths += 1
                            logger.warning(f"[BenchmarkRunner] Death detected (total={deaths})")
                except Exception as exc:
                    logger.debug(f"[BenchmarkRunner] Snapshot failed: {exc}")

        original_send = self._bridge.send_command

        async def _instrumented_send(action: str, params: dict | None = None, timeout: float = 60.0) -> dict:
            nonlocal tasks_attempted, tasks_succeeded
            if action in ("goto", "collect", "mine", "place", "craft", "attack"):
                tasks_attempted += 1
            resp = await original_send(action, params, timeout=timeout)
            if (
                action in ("goto", "collect", "mine", "place", "craft", "attack")
                and isinstance(resp, dict)
                and resp.get("status") == "success"
            ):
                tasks_succeeded += 1
            return resp

        self._bridge.send_command = _instrumented_send  # type: ignore[assignment]
        run_start = time.monotonic()
        collector_task: asyncio.Task | None = None
        limit_seconds = scenario.time_limit_minutes * 60
        try:
            collector_task = asyncio.create_task(_collect_snapshots())
            await loop.start()
            await asyncio.sleep(limit_seconds)
        except asyncio.CancelledError:
            logger.info("[BenchmarkRunner] Scenario cancelled")
        except Exception as exc:
            logger.error(f"[BenchmarkRunner] Scenario error: {exc}")
        finally:
            elapsed = time.monotonic() - run_start
            await loop.stop()
            if collector_task:
                collector_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await collector_task
            self._bridge.send_command = original_send  # type: ignore[assignment]

        final_inventory = dict(snapshots[-1].inventory) if snapshots else {}
        total_distance = 0.0
        for i in range(1, len(snapshots)):
            prev = (snapshots[i - 1].x, snapshots[i - 1].y, snapshots[i - 1].z)
            curr = (snapshots[i].x, snapshots[i].y, snapshots[i].z)
            total_distance += _l1_distance(prev, curr)

        end_skills = len(await run_library.get_all_skills())
        end_learned = len(await run_library.get_learned_skills())
        skills_created = max(0, end_learned - start_learned)
        skills_reused = max(0, (end_skills - end_learned) - (start_skills - start_learned))
        task_success_rate = tasks_succeeded / tasks_attempted if tasks_attempted > 0 else 0.0

        bridge_status: dict[str, Any] = {}
        try:
            status_resp = await self._bridge.send_command("status", timeout=10.0)
            bridge_status = status_resp.get("result", {})
        except Exception:
            pass

        all_skills_snapshot = await run_library.get_all_skills() if run_library else []
        criteria_fn = {
            "Survival Challenge": lambda: _check_survival_criteria(
                BenchmarkMetrics(deaths=deaths, final_inventory=final_inventory),
                scenario.success_criteria,
                final_inventory,
            ),
            "Building Challenge": lambda: _check_building_criteria(
                BenchmarkMetrics(final_inventory=final_inventory),
                scenario.success_criteria,
                bridge_status,
            ),
            "Learning Challenge": lambda: _check_learning_criteria(
                BenchmarkMetrics(tasks_succeeded=tasks_succeeded, skills_created=skills_created),
                scenario.success_criteria,
            ),
            "Tech Tree Unlock": lambda: _check_tech_tree_criteria(
                BenchmarkMetrics(deaths=deaths, final_inventory=final_inventory),
                scenario.success_criteria,
                len(all_skills_snapshot),
            ),
        }
        checker = criteria_fn.get(scenario.name)
        completed = checker() if checker else False
        milestone_time = elapsed if completed else 0.0
        metrics = BenchmarkMetrics(
            time_to_milestone=milestone_time,
            unique_items_collected=_count_unique_items(final_inventory),
            distance_traveled=total_distance,
            skills_created=skills_created,
            skills_reused=skills_reused,
            task_success_rate=task_success_rate,
            deaths=deaths,
            final_inventory=final_inventory,
            completed=completed,
            elapsed_seconds=elapsed,
            tasks_attempted=tasks_attempted,
            tasks_succeeded=tasks_succeeded,
        )
        logger.info(
            f"[BenchmarkRunner] '{scenario.name}' ({config.mode.value}) completed: "
            f"success={completed}, items={metrics.unique_items_collected}, "
            f"distance={metrics.distance_traveled:.0f}, deaths={deaths}, "
            f"skills_created={skills_created}, task_rate={task_success_rate:.1%}"
        )
        return metrics

    async def run_full_benchmark(
        self,
        scenarios: list[BenchmarkScenario] | None = None,
        configs: list[BenchmarkConfig] | None = None,
    ) -> dict[str, dict[str, BenchmarkMetrics]]:
        scenarios = scenarios or ALL_SCENARIOS
        configs = configs or ALL_CONFIGS
        if any(config.mode == BenchmarkMode.PREDEFINED for config in configs):
            await self.load_predefined_skills()
        results: dict[str, dict[str, BenchmarkMetrics]] = {}
        total_runs = len(scenarios) * len(configs)
        run_idx = 0
        logger.info(
            f"[BenchmarkRunner] Starting full benchmark: {len(scenarios)} scenarios x "
            f"{len(configs)} configs = {total_runs} runs"
        )
        for scenario in scenarios:
            results[scenario.name] = {}
            for config in configs:
                run_idx += 1
                logger.info(f"[BenchmarkRunner] Run {run_idx}/{total_runs}: {scenario.name} x {config.name}")
                results[scenario.name][config.name] = await self.run_scenario(scenario, config)
        logger.info(f"[BenchmarkRunner] Full benchmark completed ({total_runs} runs)")
        return results

    async def run_tech_tree_benchmark(self, config: BenchmarkConfig | None = None) -> BenchmarkMetrics:
        from .defaults import create_default_tech_tree
        from .runner import TechTreeRunner

        config = config or BenchmarkConfig(
            name="Full Voyager (Tech Tree)",
            mode=BenchmarkMode.FULL_VOYAGER,
            time_limit_minutes=60,
        )
        logger.info(
            f"[BenchmarkRunner] Starting tech tree benchmark: mode={config.mode.value}, "
            f"limit={config.time_limit_minutes}min"
        )
        run_library = SkillLibrary()
        if config.mode == BenchmarkMode.PREDEFINED:
            for skill in self._predefined_skills:
                await run_library.save_skill(skill)
        elif config.mode == BenchmarkMode.FULL_VOYAGER:
            for skill in await self._skill_library.get_all_skills():
                await run_library.save_skill(skill)
        tree_config = create_default_tech_tree()
        tree_config.total_time_budget_minutes = config.time_limit_minutes
        runner = TechTreeRunner(bridge=self._bridge, skill_library=run_library, config=tree_config)
        try:
            tree_metrics = await runner.run()
        except asyncio.CancelledError:
            logger.info("[BenchmarkRunner] Tech tree benchmark cancelled")
            tree_metrics = runner.generate_report().metrics
        except Exception as exc:
            logger.error(f"[BenchmarkRunner] Tech tree benchmark error: {exc}")
            tree_metrics = runner.generate_report().metrics
        benchmark = runner.generate_benchmark_metrics()
        logger.info(
            f"[BenchmarkRunner] Tech tree benchmark completed: phases={len(tree_metrics.phases_completed)}/4, "
            f"skills_reused={tree_metrics.skills_reused}, deaths={tree_metrics.deaths}"
        )
        return benchmark

    def generate_report(self, results: dict[str, dict[str, BenchmarkMetrics]]) -> str:
        return generate_benchmark_report(results)
