"""
Tech Tree — phase-based progression system for MC Bot Voyager.

Defines a structured unlock path from wood-tier to diamond-tier, each phase
specifying time budgets, required items, and skills to learn.  The autonomous
loop uses these phases to set short-term goals and track progress.

Architecture:
    TechTreeConfig
      └── phases: list[TechTreePhase]
            ├── WOOD   (10 min)  → wooden_pickaxe, wooden_sword, crafting_table
            ├── STONE  (15 min)  → stone_pickaxe, stone_sword, furnace
            ├── IRON   (20 min)  → iron_pickaxe, iron_sword, iron_chestplate
            └── DIAMOND (15 min) → diamond_pickaxe, diamond_sword

    TechTreeRunner
      ├── run()               → iterate all phases sequentially
      ├── _run_phase()        → execute tasks within time budget
      ├── _check_milestone()  → verify phase completion via inventory
      ├── _execute_task()     → dispatch to bridge (with skill fallback)
      └── _generate_tasks()   → phase-specific task sequences
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from .benchmark import BenchmarkMetrics
    from .bridge import MinecraftBridge
    from .skill_library import SkillLibrary


# ── Data Classes ──────────────────────────────────────────────────────────────


@dataclass
class TechTreePhase:
    """A single phase in the tech tree progression.

    Each phase represents a material tier with associated crafting goals,
    time constraints, and skills the bot should learn or reuse.
    """

    name: str
    """Phase identifier: 'wood', 'stone', 'iron', or 'diamond'."""

    time_budget_minutes: int
    """Maximum minutes the bot should spend in this phase."""

    required_items: dict[str, int]
    """Mapping of item name to required count that must be crafted/collected
    before the phase is considered complete."""

    skills_to_learn: list[str]
    """Skill names the bot should acquire during this phase."""

    description: str
    """Human-readable description of the phase objective."""

    @property
    def time_budget_seconds(self) -> float:
        """Time budget expressed in seconds."""
        return self.time_budget_minutes * 60.0

    def is_complete(self, inventory: dict[str, int]) -> bool:
        """Check whether all required items are present in *inventory*.

        Args:
            inventory: Current item counts (item_name -> count).

        Returns:
            ``True`` if every required item meets or exceeds its count.
        """
        return all(inventory.get(item, 0) >= needed for item, needed in self.required_items.items())

    def missing_items(self, inventory: dict[str, int]) -> dict[str, int]:
        """Return items that are still needed to complete this phase.

        Args:
            inventory: Current item counts.

        Returns:
            Dict of item_name -> remaining_count needed.  Empty dict means
            the phase is complete.
        """
        missing: dict[str, int] = {}
        for item, needed in self.required_items.items():
            have = inventory.get(item, 0)
            if have < needed:
                missing[item] = needed - have
        return missing


@dataclass
class TechTreeConfig:
    """Full tech tree configuration with ordered phases.

    The autonomous loop iterates through phases sequentially; each phase
    must complete (or time out) before advancing to the next.
    """

    phases: list[TechTreePhase]
    """Ordered list of phases to progress through."""

    total_time_budget_minutes: int = 60
    """Overall time budget for the entire tech tree run."""

    @property
    def total_time_budget_seconds(self) -> float:
        """Total time budget expressed in seconds."""
        return self.total_time_budget_minutes * 60.0

    def get_phase(self, name: str) -> TechTreePhase | None:
        """Look up a phase by name.

        Args:
            name: Phase name (e.g. 'iron').

        Returns:
            The matching ``TechTreePhase``, or ``None`` if not found.
        """
        for phase in self.phases:
            if phase.name == name:
                return phase
        return None

    def next_phase(self, current_name: str) -> TechTreePhase | None:
        """Return the phase that follows *current_name*, or ``None`` at the end.

        Args:
            current_name: Name of the current phase.

        Returns:
            The next ``TechTreePhase`` in sequence, or ``None``.
        """
        for i, phase in enumerate(self.phases):
            if phase.name == current_name and i + 1 < len(self.phases):
                return self.phases[i + 1]
        return None

    def validate(self) -> list[str]:
        """Validate the configuration for common misconfigurations.

        Returns:
            List of warning strings.  Empty list means valid.
        """
        warnings: list[str] = []

        if not self.phases:
            warnings.append("TechTreeConfig has no phases defined")
            return warnings

        # Check that sum of phase budgets doesn't wildly exceed total
        phase_total = sum(p.time_budget_minutes for p in self.phases)
        if phase_total > self.total_time_budget_minutes * 1.5:
            warnings.append(
                f"Sum of phase budgets ({phase_total}min) significantly exceeds "
                + f"total_time_budget ({self.total_time_budget_minutes}min)"
            )

        # Check for duplicate phase names
        names = [p.name for p in self.phases]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            warnings.append(f"Duplicate phase names: {sorted(dupes)}")

        # Warn on empty required_items
        for phase in self.phases:
            if not phase.required_items:
                warnings.append(f"Phase '{phase.name}' has no required_items")

        return warnings


@dataclass
class TechTreeMetrics:
    """Collected metrics from a tech tree run.

    Tracks progression, inventory state, skill activity, and survival
    across the entire run.
    """

    phases_completed: list[str] = field(default_factory=list)
    """Names of phases that were fully completed (all items collected)."""

    total_time_seconds: float = 0.0
    """Wall-clock time elapsed for the entire run."""

    items_collected: dict[str, int] = field(default_factory=dict)
    """Final inventory snapshot — item_name -> count."""

    skills_learned: int = 0
    """Number of new skills acquired during the run."""

    skills_reused: int = 0
    """Number of times existing skills were reused."""

    deaths: int = 0
    """Total death count during the run."""

    @property
    def completion_rate(self) -> float:
        """Fraction of predefined phases completed (0.0 – 1.0)."""
        if not _PREDEFINED_PHASES:
            return 0.0
        return len(self.phases_completed) / len(_PREDEFINED_PHASES)

    @property
    def total_skills_used(self) -> int:
        """Sum of skills learned and reused."""
        return self.skills_learned + self.skills_reused

    def summary(self) -> str:
        """One-line human-readable summary."""
        return (
            f"Phases: {len(self.phases_completed)}/{len(_PREDEFINED_PHASES)} | "
            f"Time: {self.total_time_seconds:.0f}s | "
            f"Skills: {self.skills_learned}L/{self.skills_reused}R | "
            f"Deaths: {self.deaths}"
        )


@dataclass
class TechTreeReport:
    """Complete report from a tech tree run.

    Bundles the configuration, collected metrics, per-phase details,
    and a timestamp into a single serializable object.
    """

    config: TechTreeConfig
    """The tech tree configuration used for this run."""

    metrics: TechTreeMetrics
    """Collected metrics from the run."""

    phase_details: list[dict[str, Any]] = field(default_factory=list)
    """Per-phase results.  Each dict contains:

    - ``name`` (str): Phase name.
    - ``completed`` (bool): Whether all required items were collected.
    - ``elapsed_seconds`` (float): Wall-clock time spent in this phase.
    - ``items_collected`` (dict[str, int]): Items present at phase end.
    - ``missing_items`` (dict[str, int]): Items still needed.
    """

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    """ISO-8601 timestamp of when the report was generated."""


# ── Predefined Phases ────────────────────────────────────────────────────────

WOOD_PHASE = TechTreePhase(
    name="wood",
    time_budget_minutes=10,
    required_items={
        "wooden_pickaxe": 1,
        "wooden_sword": 1,
        "crafting_table": 1,
    },
    skills_to_learn=[
        "craft_wooden_pickaxe",
        "craft_wooden_sword",
        "place_crafting_table",
    ],
    description=(
        "Gather wood, craft a crafting table, wooden pickaxe, and wooden sword. "
        "Establishes the basic toolchain for further progression."
    ),
)

STONE_PHASE = TechTreePhase(
    name="stone",
    time_budget_minutes=15,
    required_items={
        "stone_pickaxe": 1,
        "stone_sword": 1,
        "furnace": 1,
    },
    skills_to_learn=[
        "mine_cobblestone",
        "craft_furnace",
        "craft_stone_pickaxe",
        "craft_stone_sword",
    ],
    description=(
        "Mine cobblestone, build a furnace, and upgrade to stone tools. "
        "Opens access to smelting and iron-tier resources."
    ),
)

IRON_PHASE = TechTreePhase(
    name="iron",
    time_budget_minutes=20,
    required_items={
        "iron_pickaxe": 1,
        "iron_sword": 1,
        "iron_chestplate": 1,
    },
    skills_to_learn=[
        "mine_iron_ore",
        "smelt_iron_ingot",
        "craft_iron_pickaxe",
        "craft_iron_sword",
        "craft_iron_chestplate",
    ],
    description=(
        "Mine iron ore, smelt ingots, and craft iron tools plus armour. "
        "The longest phase — requires both mining depth and smelting time."
    ),
)

DIAMOND_PHASE = TechTreePhase(
    name="diamond",
    time_budget_minutes=15,
    required_items={
        "diamond_pickaxe": 1,
        "diamond_sword": 1,
    },
    skills_to_learn=[
        "mine_diamond_ore",
        "craft_diamond_pickaxe",
        "craft_diamond_sword",
    ],
    description=(
        "Mine diamonds at deep Y-levels and craft diamond tools. "
        "Final tier — completes the tech tree."
    ),
)

_PREDEFINED_PHASES: list[TechTreePhase] = [
    WOOD_PHASE,
    STONE_PHASE,
    IRON_PHASE,
    DIAMOND_PHASE,
]


# ── Factory ──────────────────────────────────────────────────────────────────


def create_default_tech_tree() -> TechTreeConfig:
    """Create the default tech tree with all four predefined phases.

    Returns:
        A ``TechTreeConfig`` with wood → stone → iron → diamond progression
        and a 60-minute total budget.

    Raises:
        RuntimeError: If the predefined configuration fails validation.
    """
    config = TechTreeConfig(
        phases=list(_PREDEFINED_PHASES),
        total_time_budget_minutes=60,
    )

    warnings = config.validate()
    if warnings:
        for w in warnings:
            logger.warning(f"[TechTree] Config warning: {w}")

    logger.info(
        "[TechTree] Created default tech tree: "
        + f"{len(config.phases)} phases, {config.total_time_budget_minutes}min budget"
    )
    return config


# ── Report Directory ─────────────────────────────────────────────────────────

_REPORT_DIR = Path("data") / "tech_tree_reports"


# ── Task Definitions ─────────────────────────────────────────────────────────
# Each phase maps to an ordered list of (task_name, bridge_action, params).
# The runner tries to find a matching skill first; if none exists, it falls
# back to the raw bridge command.


def _phase_tasks(phase_name: str) -> list[tuple[str, str, dict[str, Any]]]:
    """Return the ordered task list for *phase_name*.

    Each tuple is ``(task_label, bridge_action, params)``.

    Returns:
        Empty list for unknown phase names.
    """
    if phase_name == "wood":
        return [
            ("collect_oak_log",      "collect", {"block_type": "oak_log",      "count": 4}),
            ("craft_oak_planks",     "craft",   {"recipe": "oak_planks",       "count": 8}),
            ("craft_stick",          "craft",   {"recipe": "stick",            "count": 4}),
            ("craft_crafting_table", "craft",   {"recipe": "crafting_table",   "count": 1}),
            ("craft_wooden_pickaxe", "craft",   {"recipe": "wooden_pickaxe",   "count": 1}),
            ("craft_wooden_sword",   "craft",   {"recipe": "wooden_sword",     "count": 1}),
        ]

    if phase_name == "stone":
        return [
            ("mine_cobblestone",     "mine",    {"block_type": "stone",        "count": 8}),
            ("craft_stone_pickaxe",  "craft",   {"recipe": "stone_pickaxe",    "count": 1}),
            ("craft_stone_sword",    "craft",   {"recipe": "stone_sword",      "count": 1}),
            ("craft_furnace",        "craft",   {"recipe": "furnace",          "count": 1}),
        ]

    if phase_name == "iron":
        return [
            ("mine_iron_ore",        "collect", {"block_type": "iron_ore",     "count": 6}),
            ("smelt_iron_ingot",     "craft",   {"recipe": "iron_ingot",       "count": 6}),
            ("craft_iron_pickaxe",   "craft",   {"recipe": "iron_pickaxe",     "count": 1}),
            ("craft_iron_sword",     "craft",   {"recipe": "iron_sword",       "count": 1}),
            ("craft_iron_chestplate","craft",   {"recipe": "iron_chestplate",  "count": 1}),
        ]

    if phase_name == "diamond":
        return [
            ("mine_diamond_ore",     "collect", {"block_type": "diamond_ore",  "count": 3}),
            ("craft_diamond_pickaxe","craft",   {"recipe": "diamond_pickaxe",  "count": 1}),
            ("craft_diamond_sword",  "craft",   {"recipe": "diamond_sword",    "count": 1}),
        ]

    logger.warning(f"[TechTree] No task definition for phase '{phase_name}'")
    return []


# ── Tech Tree Runner ─────────────────────────────────────────────────────────


class TechTreeRunner:
    """Execute a full tech-tree run: iterate phases, generate tasks, check
    milestones, collect metrics, and produce reports.

    Lifecycle::

        runner = TechTreeRunner(bridge, skill_library, config)
        metrics = await runner.run()
        report = runner.generate_report()
        runner.save_report(report)

    The runner does **not** own the bridge or skill-library lifecycle — the
    caller is responsible for starting/stopping them.

    Skill integration:
        Before each task, the runner searches the skill library for a matching
        skill.  If found, it executes the skill steps; on success the skill's
        success counter is incremented and ``skills_reused`` is tracked.  On
        failure the runner falls back to a direct bridge command.
    """

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

    # ── Public API ──

    async def run(self) -> TechTreeMetrics:
        """Run the full tech tree from first phase to last.

        Iterates through phases sequentially.  Each phase must either complete
        (milestone achieved) or time out before the next phase begins.

        Returns:
            A ``TechTreeMetrics`` snapshot of the run.
        """
        self._run_start = time.monotonic()
        self._metrics = TechTreeMetrics()
        self._phase_details = []

        # Snapshot initial death count so we can compute deltas later
        self._deaths_at_start = await self._get_death_count()

        logger.info("[TechTreeRunner] Starting tech tree run")

        for phase in self._config.phases:
            # Global budget check
            elapsed = time.monotonic() - self._run_start
            if elapsed >= self._config.total_time_budget_seconds:
                logger.warning(
                    f"[TechTreeRunner] Global time budget exhausted "
                    f"({elapsed:.0f}s / {self._config.total_time_budget_seconds:.0f}s) — "
                    f"stopping before phase '{phase.name}'"
                )
                break

            completed = await self._run_phase(phase)
            if completed:
                self._metrics.phases_completed.append(phase.name)
                logger.info(f"[TechTreeRunner] Phase '{phase.name}' completed")
            else:
                logger.warning(f"[TechTreeRunner] Phase '{phase.name}' failed or timed out")

        # Finalise metrics
        self._metrics.total_time_seconds = time.monotonic() - self._run_start
        self._metrics.items_collected = await self._get_inventory()
        self._metrics.deaths = max(0, await self._get_death_count() - self._deaths_at_start)

        logger.info(f"[TechTreeRunner] Run finished — {self._metrics.summary()}")
        return self._metrics

    # ── Phase Execution ──

    async def _run_phase(self, phase: TechTreePhase) -> bool:
        """Execute all tasks within *phase* until milestone or timeout.

        Returns:
            ``True`` if the phase milestone was achieved, ``False`` on timeout.
        """
        phase_start = time.monotonic()
        budget = phase.time_budget_seconds
        tasks = _phase_tasks(phase.name)

        logger.info(
            f"[TechTreeRunner] Phase '{phase.name}' — "
            f"{len(tasks)} tasks, {phase.time_budget_minutes}min budget"
        )

        for task_label, action, params in tasks:
            # Time budget check
            elapsed = time.monotonic() - phase_start
            if elapsed >= budget:
                logger.warning(
                    f"[TechTreeRunner] Phase '{phase.name}' timed out "
                    f"({elapsed:.0f}s / {budget:.0f}s) at task '{task_label}'"
                )
                self._record_phase_detail(phase, phase_start, completed=False)
                return False

            # Execute the task (skill-aware)
            _ = await self._execute_task(task_label, action, params)

            # Milestone check after each task
            inventory = await self._get_inventory()
            if await self._check_milestone(phase, inventory):
                logger.info(
                    f"[TechTreeRunner] Phase '{phase.name}' milestone reached "
                    f"after task '{task_label}'"
                )
                self._record_phase_detail(phase, phase_start, completed=True)
                return True

        # All tasks executed — do a final milestone check
        inventory = await self._get_inventory()
        completed = await self._check_milestone(phase, inventory)
        self._record_phase_detail(phase, phase_start, completed=completed)

        if not completed:
            logger.warning(
                f"[TechTreeRunner] Phase '{phase.name}' — all tasks exhausted "
                f"but milestone not achieved (missing: {phase.missing_items(inventory)})"
            )
        return completed

    def _record_phase_detail(
        self, phase: TechTreePhase, phase_start: float, completed: bool
    ) -> None:
        """Record per-phase detail for report generation (synchronous helper)."""
        # We capture inventory snapshot at call time via a cached value;
        # actual inventory is fetched lazily in generate_report if needed.
        self._phase_details.append({
            "name": phase.name,
            "completed": completed,
            "elapsed_seconds": time.monotonic() - phase_start,
            "items_collected": dict(self._metrics.items_collected),
            "missing_items": {},
        })

    # ── Milestone Checking ──

    async def _check_milestone(
        self, phase: TechTreePhase, inventory: dict[str, int]
    ) -> bool:
        """Check whether *phase*'s required items are all present in *inventory*.

        Delegates to ``TechTreePhase.is_complete()``.
        """
        return phase.is_complete(inventory)

    # ── Task Execution ──

    async def _execute_task(
        self, task_label: str, action: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a single task, preferring a library skill if one matches.

        1. Search ``skill_library`` for a skill matching *task_label*.
        2. If found, execute the skill steps via the library.
        3. Otherwise, send the raw bridge command.

        Returns:
            The bridge response dict (``{"status": ..., "result": ...}``).
        """
        # ── Try skill library first ──
        skill = await self._find_skill(task_label)
        if skill is not None:
            logger.info(
                f"[TechTreeRunner] Task '{task_label}' — using skill '{skill.id}'"
            )
            context = await self._build_context()
            result = await self._skill_library.execute_skill_by_id(
                skill.id, self._bridge, context
            )
            if result.success:
                await self._skill_library.update_success(skill.id)
                self._metrics.skills_reused += 1
                logger.info(
                    f"[TechTreeRunner] Skill '{skill.id}' succeeded "
                    f"({result.duration:.1f}s)"
                )
                return {"status": "success", "result": result.context_updates}
            else:
                await self._skill_library.update_failure(skill.id)
                logger.warning(
                    f"[TechTreeRunner] Skill '{skill.id}' failed: {result.reason} — "
                    f"falling back to bridge command"
                )

        # ── Fallback: direct bridge command ──
        logger.info(
            f"[TechTreeRunner] Task '{task_label}' — bridge {action}({params})"
        )
        # Use longer timeout for collect/mine commands
        timeout = 120.0 if action in ("collect", "mine") else 60.0
        resp = await self._bridge.send_command(action, params, timeout=timeout)

        if resp.get("status") != "success":
            logger.warning(
                f"[TechTreeRunner] Task '{task_label}' failed: "
                f"{resp.get('result', 'unknown')}"
            )
        return resp

    # ── Helpers ──

    async def _find_skill(self, task_label: str) -> Any | None:
        """Search the skill library for a skill matching *task_label*.

        Uses keyword search on the task label (e.g. ``"craft_wooden_pickaxe"``
        → keywords ``["craft", "wooden", "pickaxe"]``).

        Returns:
            The best-matching ``Skill``, or ``None``.
        """
        # Try exact keyword match first
        matches = await self._skill_library.search_by_keyword(task_label, limit=1)
        if matches:
            return matches[0]

        # Try searching by goal description (replace underscores with spaces)
        goal = task_label.replace("_", " ")
        matches = await self._skill_library.search_skills(goal, limit=1)
        if matches:
            return matches[0]

        return None

    async def _build_context(self) -> dict[str, Any]:
        """Build a context dict for skill execution from current world state."""
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
        """Fetch the current inventory from the bot."""
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
        """Fetch the current death count from the bot status."""
        try:
            resp = await self._bridge.send_command("status", timeout=5.0)
            if resp.get("status") == "success":
                result = resp.get("result", {})
                if isinstance(result, dict):
                    return int(result.get("deaths", 0))
        except Exception:
            logger.debug("[TechTreeRunner] Could not fetch death count")
        return 0

    # ── Report Generation ─────────────────────────────────────────────────

    def generate_report(self) -> TechTreeReport:
        """Create a :class:`TechTreeReport` from the latest run results.

        Bundles the configuration, collected metrics, per-phase details,
        and a timestamp.  Call this *after* :meth:`run` completes.

        Returns:
            A ``TechTreeReport`` containing all run data.
        """
        report = TechTreeReport(
            config=self._config,
            metrics=self._metrics,
            phase_details=list(self._phase_details),
        )
        logger.info(
            f"[TechTreeRunner] Generated report: "
            f"{len(report.metrics.phases_completed)}/{len(self._config.phases)} phases, "
            f"{report.metrics.total_time_seconds:.1f}s elapsed"
        )
        return report

    def generate_markdown_report(self, report: TechTreeReport | None = None) -> str:
        """Generate a markdown summary of a tech tree run.

        Args:
            report: A ``TechTreeReport`` to summarise.  If ``None``,
                ``generate_report()`` is called automatically.

        Returns:
            Markdown-formatted report string.
        """
        if report is None:
            report = self.generate_report()

        lines: list[str] = []
        lines.append("# Tech Tree Run Report\n")
        lines.append(f"**Generated:** {report.timestamp}\n")

        # ── Overall Summary ──
        lines.append("## Summary\n")
        total_phases = len(report.config.phases)
        completed_phases = len(report.metrics.phases_completed)
        lines.append(f"- **Phases completed:** {completed_phases}/{total_phases}")
        lines.append(f"- **Total time:** {report.metrics.total_time_seconds:.1f}s "
                      f"(budget: {report.config.total_time_budget_minutes}min)")
        lines.append(f"- **Items collected:** {len(report.metrics.items_collected)} unique types")
        lines.append(f"- **Skills learned:** {report.metrics.skills_learned}")
        lines.append(f"- **Skills reused:** {report.metrics.skills_reused}")
        lines.append(f"- **Deaths:** {report.metrics.deaths}")

        completion_pct = report.metrics.completion_rate * 100
        status_icon = "✅" if completed_phases == total_phases else "⚠️"
        lines.append(f"- **Completion rate:** {status_icon} {completion_pct:.0f}%\n")

        # ── Phase Details ──
        lines.append("## Phase Details\n")
        for detail in report.phase_details:
            phase_name = detail.get("name", "unknown")
            completed = detail.get("completed", False)
            elapsed = detail.get("elapsed_seconds", 0.0)
            icon = "✅" if completed else "❌"

            lines.append(f"### {icon} {phase_name.title()} Phase\n")
            lines.append(f"- **Time spent:** {elapsed:.1f}s")

            items = detail.get("items_collected", {})
            if items:
                items_str = ", ".join(f"{k}×{v}" for k, v in sorted(items.items()) if v > 0)
                lines.append(f"- **Items:** {items_str}")

            missing = detail.get("missing_items", {})
            if missing:
                missing_str = ", ".join(f"{k} (need {v})" for k, v in sorted(missing.items()))
                lines.append(f"- **Missing:** {missing_str}")

            lines.append("")

        # ── Final Inventory ──
        lines.append("## Final Inventory\n")
        if report.metrics.items_collected:
            for item, count in sorted(report.metrics.items_collected.items()):
                if count > 0:
                    lines.append(f"- {item}: {count}")
        else:
            lines.append("*No items collected.*")
        lines.append("")

        lines.append("---\n*Report generated by TechTreeRunner*")
        return "\n".join(lines)

    # ── Report Persistence ────────────────────────────────────────────────

    def save_report(
        self,
        report: TechTreeReport | None = None,
        directory: Path | str | None = None,
    ) -> Path:
        """Save a tech tree report as a markdown file.

        Creates the report directory if it doesn't exist.  The filename
        uses the format ``YYYY-MM-DD_HHMMSS.md``.

        Args:
            report: A ``TechTreeReport`` to persist.  If ``None``,
                ``generate_report()`` is called automatically.
            directory: Target directory.  Defaults to ``data/tech_tree_reports/``.

        Returns:
            The :class:`Path` of the saved file.
        """
        if report is None:
            report = self.generate_report()

        target_dir = Path(directory) if directory else _REPORT_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        # Format: YYYY-MM-DD_HHMMSS.md
        ts = datetime.fromisoformat(report.timestamp)
        filename = ts.strftime("%Y-%m-%d_%H%M%S") + ".md"
        filepath = target_dir / filename

        markdown = self.generate_markdown_report(report)
        filepath.write_text(markdown, encoding="utf-8")

        logger.info(f"[TechTreeRunner] Report saved to {filepath}")
        return filepath

    # ── BenchmarkRunner Integration ───────────────────────────────────────

    def generate_benchmark_metrics(
        self, report: TechTreeReport | None = None
    ) -> BenchmarkMetrics:
        """Convert tech tree metrics to :class:`BenchmarkMetrics`.

        Enables integration with the existing ``BenchmarkRunner`` by
        translating tech-tree-specific fields into the generic benchmark
        format.

        Args:
            report: A ``TechTreeReport`` to convert.  If ``None``,
                ``generate_report()`` is called automatically.

        Returns:
            A ``BenchmarkMetrics`` instance populated from the tech tree run.
        """
        from .benchmark import BenchmarkMetrics

        if report is None:
            report = self.generate_report()

        m = report.metrics

        # Determine overall completion: all phases must be completed
        total_phases = len(report.config.phases)
        completed = len(m.phases_completed) >= total_phases

        # Count unique item types with count > 0
        unique_items = sum(1 for v in m.items_collected.values() if v > 0)

        benchmark = BenchmarkMetrics(
            time_to_milestone=m.total_time_seconds if completed else 0.0,
            unique_items_collected=unique_items,
            skills_created=m.skills_learned,
            skills_reused=m.skills_reused,
            deaths=m.deaths,
            final_inventory=dict(m.items_collected),
            completed=completed,
            elapsed_seconds=m.total_time_seconds,
        )

        logger.info(
            f"[TechTreeRunner] Converted to BenchmarkMetrics: "
            f"completed={completed}, items={unique_items}, "
            f"skills={m.skills_learned}+{m.skills_reused}"
        )
        return benchmark
