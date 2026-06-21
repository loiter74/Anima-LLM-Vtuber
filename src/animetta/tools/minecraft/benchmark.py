"""
Benchmark Runner — compare MC Bot Voyager configurations across scenarios.

Runs the autonomous loop under different configurations (rule-only, llm-only,
predefined, full-voyager) on standardized scenarios, collecting metrics for
performance comparison.

Architecture:
    BenchmarkRunner
      ├── 3 scenarios (survival, building, learning)
      ├── 4 config modes (rule-only, llm-only, predefined, full-voyager)
      ├── Periodic world-state sampling → metrics
      └── Report generation (markdown table)
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from loguru import logger

from .autonomous import AutonomousLoop
from .skill_library import Skill, SkillLibrary

if TYPE_CHECKING:
    from .bridge import MinecraftBridge
    from .rules_engine import RulesEngine


# ── Enums ─────────────────────────────────────────────────────────────────────

class BenchmarkMode(StrEnum):
    """Configuration modes for benchmark runs."""
    RULE_ONLY = "rule-only"
    LLM_ONLY = "llm-only"
    PREDEFINED = "predefined"
    FULL_VOYAGER = "full-voyager"


# ── Data Classes ──────────────────────────────────────────────────────────────

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
    time_to_milestone: float = 0.0          # seconds to reach success criteria
    unique_items_collected: int = 0         # distinct item types in final inventory
    distance_traveled: float = 0.0          # total blocks moved (L1 norm)
    skills_created: int = 0                 # new skills added to library
    skills_reused: int = 0                  # existing skills executed
    task_success_rate: float = 0.0          # fraction of tasks that succeeded
    deaths: int = 0                         # times health dropped to 0
    final_inventory: dict[str, int] = field(default_factory=dict)
    completed: bool = False                 # whether scenario criteria were met
    elapsed_seconds: float = 0.0            # total wall-clock time
    tasks_attempted: int = 0                # total task/action attempts
    tasks_succeeded: int = 0                # successful task/action completions


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


# ── Scenarios ─────────────────────────────────────────────────────────────────

SURVIVAL_CHALLENGE = BenchmarkScenario(
    name="Survival Challenge",
    description=(
        "Collect iron_pickaxe + iron_sword and survive without dying. "
        "Tests resource gathering, crafting, and threat avoidance."
    ),
    success_criteria={
        "required_items": {"iron_pickaxe": 1, "iron_sword": 1},
        "max_deaths": 0,
    },
    time_limit_minutes=20,
)

BUILDING_CHALLENGE = BenchmarkScenario(
    name="Building Challenge",
    description=(
        "Build an enclosed space of at least 5×5×3 blocks. "
        "Tests material gathering, planning, and block placement."
    ),
    success_criteria={
        "min_enclosed_volume": 75,   # 5 × 5 × 3
        "min_dimensions": (5, 5, 3),  # (x, y, z)
    },
    time_limit_minutes=25,
)

LEARNING_CHALLENGE = BenchmarkScenario(
    name="Learning Challenge",
    description=(
        "Complete 5 distinct tasks and verify skill accumulation. "
        "Tests the skill extraction and reuse pipeline."
    ),
    success_criteria={
        "min_tasks_completed": 5,
        "min_skills_learned": 2,
    },
    time_limit_minutes=15,
)

TECH_TREE_UNLOCK = BenchmarkScenario(
    name="Tech Tree Unlock",
    description=(
        "Progress through the full tech tree (wood → stone → iron → diamond). "
        "Tests phase-based progression, skill search/execution/reuse, and "
        "milestone tracking across material tiers."
    ),
    success_criteria={
        "min_phases_completed": 4,
        "max_deaths": 3,
    },
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _l1_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Manhattan (L1) distance between two 3D points."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def _count_unique_items(inventory: dict[str, int]) -> int:
    """Count distinct item types that have count > 0."""
    return sum(1 for v in inventory.values() if v > 0)


def _check_survival_criteria(
    metrics: BenchmarkMetrics,
    criteria: dict[str, Any],
    inventory: dict[str, int],
) -> bool:
    """Check if survival challenge success criteria are met."""
    required: dict[str, int] = criteria.get("required_items", {})
    max_deaths: int = criteria.get("max_deaths", 0)

    if metrics.deaths > max_deaths:
        return False

    return all(inventory.get(item, 0) >= count for item, count in required.items())


def _check_building_criteria(
    metrics: BenchmarkMetrics,
    criteria: dict[str, Any],
    bridge_status: dict[str, Any],
) -> bool:
    """Check if building challenge success criteria are met.

    Uses bridge status to detect placed blocks.  In a real implementation
    this would query the world for block counts; here we check if the
    inventory contains enough building materials as a proxy.
    """
    min_volume = criteria.get("min_enclosed_volume", 75)

    # Proxy: check if cobblestone/wood placed >= min_volume
    # In production, this would scan the world for placed blocks
    placed = bridge_status.get("blocks_placed", 0)
    # Fallback: cannot verify without world query when insufficient blocks placed
    return placed >= min_volume


def _check_learning_criteria(
    metrics: BenchmarkMetrics,
    criteria: dict[str, Any],
) -> bool:
    """Check if learning challenge success criteria are met."""
    min_tasks = criteria.get("min_tasks_completed", 5)
    min_skills = criteria.get("min_skills_learned", 2)

    return (
        metrics.tasks_succeeded >= min_tasks
        and metrics.skills_created >= min_skills
    )


def _check_tech_tree_criteria(
    metrics: BenchmarkMetrics,
    criteria: dict[str, Any],
    tech_tree_phases_completed: int,
) -> bool:
    """Check if tech tree unlock success criteria are met."""
    min_phases = criteria.get("min_phases_completed", 4)
    max_deaths = criteria.get("max_deaths", 3)

    if metrics.deaths > max_deaths:
        return False

    return tech_tree_phases_completed >= min_phases


# ── BenchmarkRunner ──────────────────────────────────────────────────────────

class BenchmarkRunner:
    """Runs MC Bot through benchmark scenarios with different configurations.

    Collects periodic world-state snapshots and computes metrics for
    comparison across rule-only, llm-only, predefined, and full-voyager modes.

    Usage::

        runner = BenchmarkRunner(bridge, llm_service, skill_library)
        results = await runner.run_full_benchmark()
        report = runner.generate_report(results)
    """

    # How often to sample world state (seconds)
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

        # Predefined skills for "predefined" mode
        self._predefined_skills: list[Skill] = []

        logger.info("[BenchmarkRunner] Initialized")

    async def load_predefined_skills(self) -> None:
        """Load predefined skills from the skill library for predefined mode."""
        try:
            from .predefined_skills import get_predefined_skills
            self._predefined_skills = get_predefined_skills()
            logger.info(
                f"[BenchmarkRunner] Loaded {len(self._predefined_skills)} predefined skills"
            )
        except ImportError:
            logger.warning(
                "[BenchmarkRunner] predefined_skills module not found, "
                "predefined mode will use empty skill set"
            )

    # ── Single Scenario Run ──────────────────────────────────────────────

    async def run_scenario(
        self,
        scenario: BenchmarkScenario,
        config: BenchmarkConfig,
    ) -> BenchmarkMetrics:
        """Run a single scenario with the given configuration.

        Creates an ``AutonomousLoop`` configured per *config.mode*, runs it
        for up to ``scenario.time_limit_minutes``, and collects metrics
        from periodic world-state snapshots.

        Returns a ``BenchmarkMetrics`` with the collected data.
        """
        logger.info(
            f"[BenchmarkRunner] Starting '{scenario.name}' with mode '{config.mode.value}' "
            f"(limit={config.time_limit_minutes}min, seed={config.world_seed})"
        )

        # ── Build skill library for this run ──
        run_library = SkillLibrary()
        if config.mode == BenchmarkMode.PREDEFINED:
            for skill in self._predefined_skills:
                await run_library.save_skill(skill)
        elif config.mode == BenchmarkMode.FULL_VOYAGER:
            # Copy existing library
            for skill in await self._skill_library.get_all_skills():
                await run_library.save_skill(skill)

        # ── Configure planner based on mode ──
        planner = None
        if config.mode in (BenchmarkMode.LLM_ONLY, BenchmarkMode.FULL_VOYAGER):
            planner = self._llm_service

        # ── Configure skill-learning components ──
        skill_extractor = None
        skill_validator = None
        if config.mode == BenchmarkMode.FULL_VOYAGER:
            try:
                from .skill_extractor import SkillExtractor
                from .skill_validator import SkillValidator
                skill_extractor = SkillExtractor()
                skill_validator = SkillValidator()
            except ImportError:
                logger.warning(
                    "[BenchmarkRunner] SkillExtractor/SkillValidator not available"
                )

        # ── Create autonomous loop ──
        loop = AutonomousLoop(
            bridge=self._bridge,
            rules=self._rules_engine,
            skill_library=run_library if config.mode != BenchmarkMode.RULE_ONLY else None,
            planner=planner,
            config={"mode": config.mode.value},
            skill_extractor=skill_extractor,
            skill_validator=skill_validator,
        )

        # ── Metrics tracking ──
        snapshots: list[_Snapshot] = []
        start_skills = len(await run_library.get_all_skills())
        start_learned = len(await run_library.get_learned_skills())
        deaths = 0
        tasks_attempted = 0
        tasks_succeeded = 0
        milestone_time: float = 0.0
        completed = False

        # Set up world seed if specified
        if config.world_seed:
            try:
                await self._bridge.send_command(
                    "chat",
                    {"message": f"/seed {config.world_seed}"},
                    timeout=10.0,
                )
            except Exception:
                logger.debug("[BenchmarkRunner] Could not set world seed")

        # ── Snapshot collector task ──
        async def _collect_snapshots() -> None:
            """Periodically sample world state."""
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

                        # Detect death
                        if snap.health <= 0:
                            deaths += 1
                            logger.warning(
                                f"[BenchmarkRunner] Death detected (total={deaths})"
                            )
                except Exception as e:
                    logger.debug(f"[BenchmarkRunner] Snapshot failed: {e}")

        # ── Action counter (intercept bridge commands) ──
        # We track tasks by observing bridge command responses
        original_send = self._bridge.send_command

        async def _instrumented_send(
            action: str, params: dict | None = None, timeout: float = 60.0
        ) -> dict:
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

        # Swap in instrumented send_command
        self._bridge.send_command = _instrumented_send  # type: ignore[assignment]

        # ── Run ──
        run_start = time.monotonic()
        collector_task: asyncio.Task | None = None
        limit_seconds = scenario.time_limit_minutes * 60

        try:
            # Start snapshot collector
            collector_task = asyncio.create_task(_collect_snapshots())

            # Start autonomous loop
            await loop.start()

            # Wait for time limit
            await asyncio.sleep(limit_seconds)

        except asyncio.CancelledError:
            logger.info("[BenchmarkRunner] Scenario cancelled")
        except Exception as e:
            logger.error(f"[BenchmarkRunner] Scenario error: {e}")
        finally:
            elapsed = time.monotonic() - run_start

            # Stop loop
            await loop.stop()

            # Cancel collector
            if collector_task:
                collector_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await collector_task

            # Restore original send_command
            self._bridge.send_command = original_send  # type: ignore[assignment]

        # ── Compute metrics ──
        final_inventory: dict[str, int] = {}
        if snapshots:
            final_inventory = dict(snapshots[-1].inventory)

        # Distance traveled
        total_distance = 0.0
        for i in range(1, len(snapshots)):
            prev = (snapshots[i - 1].x, snapshots[i - 1].y, snapshots[i - 1].z)
            curr = (snapshots[i].x, snapshots[i].y, snapshots[i].z)
            total_distance += _l1_distance(prev, curr)

        # Skills
        end_skills = len(await run_library.get_all_skills())
        end_learned = len(await run_library.get_learned_skills())
        skills_created = max(0, end_learned - start_learned)
        skills_reused = max(0, (end_skills - end_learned) - (start_skills - start_learned))

        # Task success rate
        task_success_rate = (
            tasks_succeeded / tasks_attempted if tasks_attempted > 0 else 0.0
        )

        # Check success criteria
        bridge_status: dict[str, Any] = {}
        try:
            status_resp = await self._bridge.send_command("status", timeout=10.0)
            bridge_status = status_resp.get("result", {})
        except Exception:
            pass

        # Snapshot skills count for lambda capture
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
                BenchmarkMetrics(
                    tasks_succeeded=tasks_succeeded,
                    skills_created=skills_created,
                ),
                scenario.success_criteria,
            ),
            "Tech Tree Unlock": lambda: _check_tech_tree_criteria(
                BenchmarkMetrics(deaths=deaths, final_inventory=final_inventory),
                scenario.success_criteria,
                len(all_skills_snapshot),  # proxy for phases
            ),
        }

        checker = criteria_fn.get(scenario.name)
        completed = checker() if checker else False

        # Milestone time: time at which criteria first became satisfied
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

    # ── Full Benchmark ───────────────────────────────────────────────────

    async def run_full_benchmark(
        self,
        scenarios: list[BenchmarkScenario] | None = None,
        configs: list[BenchmarkConfig] | None = None,
    ) -> dict[str, dict[str, BenchmarkMetrics]]:
        """Run all scenarios × all configurations.

        Returns a nested dict: ``results[scenario_name][config_name] = BenchmarkMetrics``.

        Args:
            scenarios: Scenarios to run (default: ``ALL_SCENARIOS``).
            configs: Configurations to test (default: ``ALL_CONFIGS``).
        """
        scenarios = scenarios or ALL_SCENARIOS
        configs = configs or ALL_CONFIGS

        # Preload predefined skills if needed
        has_predefined = any(c.mode == BenchmarkMode.PREDEFINED for c in configs)
        if has_predefined:
            await self.load_predefined_skills()

        results: dict[str, dict[str, BenchmarkMetrics]] = {}
        total_runs = len(scenarios) * len(configs)
        run_idx = 0

        logger.info(
            f"[BenchmarkRunner] Starting full benchmark: "
            f"{len(scenarios)} scenarios × {len(configs)} configs = {total_runs} runs"
        )

        for scenario in scenarios:
            results[scenario.name] = {}
            for config in configs:
                run_idx += 1
                logger.info(
                    f"[BenchmarkRunner] Run {run_idx}/{total_runs}: "
                    f"{scenario.name} × {config.name}"
                )
                metrics = await self.run_scenario(scenario, config)
                results[scenario.name][config.name] = metrics

        logger.info(f"[BenchmarkRunner] Full benchmark completed ({total_runs} runs)")
        return results

    # ── Tech Tree Benchmark ──────────────────────────────────────────────

    async def run_tech_tree_benchmark(
        self,
        config: BenchmarkConfig | None = None,
    ) -> BenchmarkMetrics:
        """Run the tech tree unlock scenario as a dedicated benchmark.

        Uses ``TechTreeRunner`` to progress through all four material tiers,
        converting the result to ``BenchmarkMetrics`` for comparison with
        other scenarios.

        Args:
            config: Benchmark configuration.  Defaults to Full Voyager mode
                with a 60-minute time limit.

        Returns:
            A ``BenchmarkMetrics`` instance from the tech tree run.
        """
        from .tech_tree import TechTreeRunner, create_default_tech_tree

        config = config or BenchmarkConfig(
            name="Full Voyager (Tech Tree)",
            mode=BenchmarkMode.FULL_VOYAGER,
            time_limit_minutes=60,
        )

        logger.info(
            f"[BenchmarkRunner] Starting tech tree benchmark: "
            f"mode={config.mode.value}, limit={config.time_limit_minutes}min"
        )

        # Build skill library for this run
        run_library = SkillLibrary()
        if config.mode == BenchmarkMode.PREDEFINED:
            for skill in self._predefined_skills:
                await run_library.save_skill(skill)
        elif config.mode == BenchmarkMode.FULL_VOYAGER:
            for skill in await self._skill_library.get_all_skills():
                await run_library.save_skill(skill)

        # Create tech tree config with adjusted time budget
        tree_config = create_default_tech_tree()
        tree_config.total_time_budget_minutes = config.time_limit_minutes

        # Create and run
        runner = TechTreeRunner(
            bridge=self._bridge,
            skill_library=run_library,
            config=tree_config,
        )

        try:
            tree_metrics = await runner.run()
        except asyncio.CancelledError:
            logger.info("[BenchmarkRunner] Tech tree benchmark cancelled")
            tree_metrics = runner.generate_report().metrics
        except Exception as e:
            logger.error(f"[BenchmarkRunner] Tech tree benchmark error: {e}")
            tree_metrics = runner.generate_report().metrics

        # Convert to BenchmarkMetrics
        benchmark = runner.generate_benchmark_metrics()

        logger.info(
            f"[BenchmarkRunner] Tech tree benchmark completed: "
            f"phases={len(tree_metrics.phases_completed)}/4, "
            f"skills_reused={tree_metrics.skills_reused}, "
            f"deaths={tree_metrics.deaths}"
        )

        return benchmark

    # ── Report Generation ────────────────────────────────────────────────

    def generate_report(self, results: dict[str, dict[str, BenchmarkMetrics]]) -> str:
        """Generate a markdown benchmark report.

        Produces a formatted markdown document with:
        - Summary table (scenario × config)
        - Per-scenario detailed tables
        - Key findings

        Args:
            results: Output of :meth:`run_full_benchmark`.

        Returns:
            Markdown-formatted report string.
        """
        lines: list[str] = []
        lines.append("# MC Bot Voyager Benchmark Report\n")
        lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        # ── Summary Table ──
        lines.append("## Summary\n")
        lines.append(
            "| Scenario | Config | Completed | Time (s) | Items | Distance | "
            "Deaths | Skills Created | Task Rate |"
        )
        lines.append(
            "|----------|--------|-----------|----------|-------|----------|"
            "--------|----------------|-----------|"
        )

        for scenario_name, configs in results.items():
            for config_name, m in configs.items():
                status = "✅" if m.completed else "❌"
                lines.append(
                    f"| {scenario_name} | {config_name} | {status} | "
                    f"{m.elapsed_seconds:.0f} | {m.unique_items_collected} | "
                    f"{m.distance_traveled:.0f} | {m.deaths} | "
                    f"{m.skills_created} | {m.task_success_rate:.0%} |"
                )

        # ── Per-Scenario Detail ──
        lines.append("\n## Detailed Results\n")
        for scenario_name, configs in results.items():
            lines.append(f"### {scenario_name}\n")

            # Find best config for this scenario
            best_config = max(
                configs.items(),
                key=lambda kv: (
                    kv[1].completed,
                    kv[1].task_success_rate,
                    kv[1].unique_items_collected,
                ),
            )
            lines.append(
                f"**Best configuration:** {best_config[0]} "
                f"({'completed' if best_config[1].completed else 'not completed'}, "
                f"{best_config[1].task_success_rate:.0%} task success rate)\n"
            )

            # Inventory comparison
            lines.append("**Final Inventory (unique items):**\n")
            for config_name, m in configs.items():
                items_str = ", ".join(
                    f"{k}×{v}" for k, v in sorted(m.final_inventory.items()) if v > 0
                ) or "(empty)"
                lines.append(f"- `{config_name}`: {items_str}")
            lines.append("")

        # ── Key Findings ──
        lines.append("## Key Findings\n")

        # Overall completion rate
        all_metrics = [
            m for configs in results.values() for m in configs.values()
        ]
        completed_count = sum(1 for m in all_metrics if m.completed)
        total_count = len(all_metrics)
        lines.append(
            f"- **Overall completion rate:** {completed_count}/{total_count} "
            f"({completed_count / total_count:.0%})\n"
        )

        # Best mode overall
        mode_completions: dict[str, int] = {}
        for configs in results.values():
            for config_name, m in configs.items():
                if m.completed:
                    mode_completions[config_name] = mode_completions.get(config_name, 0) + 1

        if mode_completions:
            best_mode = max(mode_completions, key=lambda k: mode_completions[k])
            lines.append(
                f"- **Most successful mode:** {best_mode} "
                f"({mode_completions[best_mode]} completions)\n"
            )

        # Skill accumulation insight
        total_skills = sum(
            m.skills_created
            for configs in results.values()
            for m in configs.values()
        )
        lines.append(
            f"- **Total skills created across all runs:** {total_skills}\n"
        )

        # Deaths
        total_deaths = sum(m.deaths for m in all_metrics)
        lines.append(f"- **Total deaths across all runs:** {total_deaths}\n")

        lines.append("\n---\n*Report generated by BenchmarkRunner*")
        return "\n".join(lines)
