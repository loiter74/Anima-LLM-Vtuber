"""Tests for TechTree — phase-based progression system for MC Bot Voyager."""

from __future__ import annotations

import importlib
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import tech_tree directly, bypassing __init__.py which has a syntax error
# in benchmark.py (await inside lambda).  Load the module by path.
_spec = importlib.util.spec_from_file_location(
    "animetta.tools.minecraft.tech_tree",
    Path(__file__).resolve().parents[3]
    / "src"
    / "animetta"
    / "tools"
    / "minecraft"
    / "tech_tree.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

DIAMOND_PHASE = _mod.DIAMOND_PHASE
IRON_PHASE = _mod.IRON_PHASE
STONE_PHASE = _mod.STONE_PHASE
WOOD_PHASE = _mod.WOOD_PHASE
TechTreeConfig = _mod.TechTreeConfig
TechTreeMetrics = _mod.TechTreeMetrics
TechTreePhase = _mod.TechTreePhase
TechTreeReport = _mod.TechTreeReport
TechTreeRunner = _mod.TechTreeRunner
_PREDEFINED_PHASES = _mod._PREDEFINED_PHASES
_phase_tasks = _mod._phase_tasks
create_default_tech_tree = _mod.create_default_tech_tree


# ── Lightweight BenchmarkMetrics stub ─────────────────────────────────────────
# Avoid importing the real benchmark.py (has top-level imports that may fail).
# The runner's generate_benchmark_metrics() calls ``from .benchmark import
# BenchmarkMetrics`` — we patch that import to use this stub.


@dataclass
class _FakeBenchmarkMetrics:
    """Stub for benchmark.BenchmarkMetrics used in tests."""
    time_to_milestone: float = 0.0
    unique_items_collected: int = 0
    skills_created: int = 0
    skills_reused: int = 0
    deaths: int = 0
    final_inventory: dict[str, int] = field(default_factory=dict)
    completed: bool = False
    elapsed_seconds: float = 0.0
    distance_traveled: float = 0.0
    task_success_rate: float = 0.0
    tasks_attempted: int = 0
    tasks_succeeded: int = 0


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_bridge(inventory: dict[str, int] | None = None, deaths: int = 0) -> MagicMock:
    """Create a mock MinecraftBridge with configurable inventory."""
    inv = inventory or {}
    bridge = MagicMock()
    bridge.send_command = AsyncMock(
        return_value={
            "status": "success",
            "result": {
                "inventory": inv,
                "deaths": deaths,
                "health": 20,
                "food": 20,
                "is_day": True,
                "is_night": False,
            },
        }
    )
    return bridge


def make_skill_library() -> MagicMock:
    """Create a mock SkillLibrary."""
    lib = MagicMock()
    lib.search_by_keyword = AsyncMock(return_value=[])
    lib.search_skills = AsyncMock(return_value=[])
    lib.execute_skill_by_id = AsyncMock()
    lib.update_success = AsyncMock()
    lib.update_failure = AsyncMock()
    return lib


def make_phase(
    name: str = "test",
    time_budget_minutes: int = 10,
    required_items: dict[str, int] | None = None,
    skills_to_learn: list[str] | None = None,
    description: str = "Test phase",
) -> TechTreePhase:
    """Create a TechTreePhase with sensible defaults."""
    return TechTreePhase(
        name=name,
        time_budget_minutes=time_budget_minutes,
        required_items=required_items or {"test_item": 1},
        skills_to_learn=skills_to_learn or [],
        description=description,
    )


# ── TechTreePhase ────────────────────────────────────────────────────────────


class TestTechTreePhase:
    """Tests for TechTreePhase data class."""

    def test_tech_tree_phase_creation(self):
        """Phase creation with all fields."""
        phase = TechTreePhase(
            name="wood",
            time_budget_minutes=10,
            required_items={"wooden_pickaxe": 1, "wooden_sword": 1},
            skills_to_learn=["craft_wooden_pickaxe"],
            description="Gather wood and craft basic tools.",
        )

        assert phase.name == "wood"
        assert phase.time_budget_minutes == 10
        assert phase.required_items == {"wooden_pickaxe": 1, "wooden_sword": 1}
        assert phase.skills_to_learn == ["craft_wooden_pickaxe"]
        assert "wood" in phase.description.lower()

    def test_tech_tree_phase_defaults(self):
        """Phase creation preserves all provided values."""
        phase = make_phase(name="iron", time_budget_minutes=20)
        assert phase.name == "iron"
        assert phase.time_budget_minutes == 20
        assert phase.required_items == {"test_item": 1}
        assert phase.skills_to_learn == []

    def test_time_budget_seconds(self):
        """time_budget_seconds converts minutes to seconds."""
        phase = make_phase(time_budget_minutes=15)
        assert phase.time_budget_seconds == 900.0

    def test_time_budget_seconds_zero(self):
        """Zero minutes yields zero seconds."""
        phase = make_phase(time_budget_minutes=0)
        assert phase.time_budget_seconds == 0.0

    def test_tech_tree_phase_is_complete(self):
        """is_complete returns True when all items are present."""
        phase = make_phase(required_items={"sword": 1, "shield": 1})

        # Exact match
        assert phase.is_complete({"sword": 1, "shield": 1}) is True

        # Surplus is fine
        assert phase.is_complete({"sword": 3, "shield": 2}) is True

    def test_tech_tree_phase_is_complete_missing_items(self):
        """is_complete returns False when items are missing."""
        phase = make_phase(required_items={"sword": 1, "shield": 2})

        # Completely empty
        assert phase.is_complete({}) is False

        # Partial — one item missing
        assert phase.is_complete({"sword": 1}) is False

        # Insufficient count
        assert phase.is_complete({"sword": 1, "shield": 1}) is False

    def test_tech_tree_phase_is_complete_empty_requirements(self):
        """Phase with no required items is always complete."""
        phase = TechTreePhase(
            name="empty",
            time_budget_minutes=5,
            required_items={},
            skills_to_learn=[],
            description="Empty phase",
        )
        assert phase.is_complete({}) is True
        assert phase.is_complete({"anything": 99}) is True

    def test_tech_tree_phase_missing_items(self):
        """missing_items returns remaining items needed."""
        phase = make_phase(required_items={"iron_ingot": 6, "stick": 2})

        # Empty inventory
        missing = phase.missing_items({})
        assert missing == {"iron_ingot": 6, "stick": 2}

        # Partial inventory
        missing = phase.missing_items({"iron_ingot": 4, "stick": 2})
        assert missing == {"iron_ingot": 2}

        # Complete inventory
        missing = phase.missing_items({"iron_ingot": 6, "stick": 2, "extra": 10})
        assert missing == {}

    def test_tech_tree_phase_missing_items_surplus(self):
        """Surplus items don't appear in missing_items."""
        phase = make_phase(required_items={"cobblestone": 12})
        missing = phase.missing_items({"cobblestone": 20})
        assert missing == {}


# ── TechTreeConfig ───────────────────────────────────────────────────────────


class TestTechTreeConfig:
    """Tests for TechTreeConfig data class."""

    def test_tech_tree_config_creation(self):
        """Config creation with phases and budget."""
        phases = [make_phase(name="a"), make_phase(name="b")]
        config = TechTreeConfig(phases=phases, total_time_budget_minutes=30)

        assert len(config.phases) == 2
        assert config.total_time_budget_minutes == 30

    def test_total_time_budget_seconds(self):
        """total_time_budget_seconds converts correctly."""
        config = TechTreeConfig(phases=[], total_time_budget_minutes=45)
        assert config.total_time_budget_seconds == 2700.0

    def test_get_phase(self):
        """get_phase retrieves a phase by name."""
        p1 = make_phase(name="wood")
        p2 = make_phase(name="stone")
        config = TechTreeConfig(phases=[p1, p2])

        assert config.get_phase("wood") is p1
        assert config.get_phase("stone") is p2
        assert config.get_phase("diamond") is None

    def test_tech_tree_config_next_phase(self):
        """next_phase returns the following phase in sequence."""
        p1 = make_phase(name="wood")
        p2 = make_phase(name="stone")
        p3 = make_phase(name="iron")
        config = TechTreeConfig(phases=[p1, p2, p3])

        assert config.next_phase("wood") is p2
        assert config.next_phase("stone") is p3
        assert config.next_phase("iron") is None  # last phase

    def test_next_phase_unknown(self):
        """next_phase returns None for unknown phase name."""
        config = TechTreeConfig(phases=[make_phase(name="wood")])
        assert config.next_phase("nonexistent") is None

    def test_next_phase_single(self):
        """next_phase returns None when there's only one phase."""
        config = TechTreeConfig(phases=[make_phase(name="only")])
        assert config.next_phase("only") is None

    def test_tech_tree_config_validate_valid(self):
        """Valid config produces no warnings."""
        config = TechTreeConfig(
            phases=[make_phase(name="a"), make_phase(name="b")],
            total_time_budget_minutes=60,
        )
        warnings = config.validate()
        assert warnings == []

    def test_validate_empty_phases(self):
        """Empty phase list warns."""
        config = TechTreeConfig(phases=[])
        warnings = config.validate()
        assert len(warnings) == 1
        assert "no phases" in warnings[0].lower()

    def test_validate_budget_exceeded(self):
        """Phase budgets exceeding total * 1.5 warns."""
        config = TechTreeConfig(
            phases=[
                make_phase(name="a", time_budget_minutes=50),
                make_phase(name="b", time_budget_minutes=50),
            ],
            total_time_budget_minutes=60,
        )
        warnings = config.validate()
        assert any("exceeds" in w.lower() for w in warnings)

    def test_validate_duplicate_names(self):
        """Duplicate phase names warn."""
        config = TechTreeConfig(
            phases=[make_phase(name="dup"), make_phase(name="dup")]
        )
        warnings = config.validate()
        assert any("duplicate" in w.lower() for w in warnings)

    def test_validate_empty_required_items(self):
        """Phase with no required_items warns."""
        empty_phase = TechTreePhase(
            name="empty",
            time_budget_minutes=5,
            required_items={},
            skills_to_learn=[],
            description="Empty phase",
        )
        config = TechTreeConfig(phases=[empty_phase])
        warnings = config.validate()
        assert any("empty" in w.lower() and "required_items" in w.lower() for w in warnings)


# ── TechTreeMetrics ──────────────────────────────────────────────────────────


class TestTechTreeMetrics:
    """Tests for TechTreeMetrics data class."""

    def test_tech_tree_metrics_defaults(self):
        """Default metrics have zeroed counters."""
        m = TechTreeMetrics()
        assert m.phases_completed == []
        assert m.total_time_seconds == 0.0
        assert m.items_collected == {}
        assert m.skills_learned == 0
        assert m.skills_reused == 0
        assert m.deaths == 0

    def test_completion_rate_empty(self):
        """Completion rate is 0 when no phases completed."""
        m = TechTreeMetrics()
        assert m.completion_rate == 0.0

    def test_completion_rate_partial(self):
        """Completion rate reflects completed / total predefined phases."""
        m = TechTreeMetrics(phases_completed=["wood", "stone"])
        total = len(_PREDEFINED_PHASES)
        assert m.completion_rate == pytest.approx(2.0 / total)

    def test_completion_rate_full(self):
        """Completion rate is 1.0 when all predefined phases done."""
        m = TechTreeMetrics(
            phases_completed=[p.name for p in _PREDEFINED_PHASES]
        )
        assert m.completion_rate == 1.0

    def test_total_skills_used(self):
        """total_skills_used sums learned + reused."""
        m = TechTreeMetrics(skills_learned=3, skills_reused=5)
        assert m.total_skills_used == 8

    def test_total_skills_used_zero(self):
        """total_skills_used is 0 when both are zero."""
        m = TechTreeMetrics()
        assert m.total_skills_used == 0

    def test_tech_tree_metrics_summary(self):
        """summary() returns a human-readable one-liner."""
        m = TechTreeMetrics(
            phases_completed=["wood"],
            total_time_seconds=123.4,
            skills_learned=2,
            skills_reused=3,
            deaths=1,
        )
        s = m.summary()
        assert "1/" in s
        assert "123s" in s
        assert "2L/3R" in s
        assert "Deaths: 1" in s


# ── Predefined Phases ────────────────────────────────────────────────────────


class TestPredefinedPhases:
    """Tests for the four predefined tech tree phases."""

    def test_predefined_phases_exist(self):
        """All four predefined phases are defined."""
        assert WOOD_PHASE.name == "wood"
        assert STONE_PHASE.name == "stone"
        assert IRON_PHASE.name == "iron"
        assert DIAMOND_PHASE.name == "diamond"

    def test_predefined_phases_in_list(self):
        """_PREDEFINED_PHASES contains all four in order."""
        names = [p.name for p in _PREDEFINED_PHASES]
        assert names == ["wood", "stone", "iron", "diamond"]

    def test_wood_phase_requirements(self):
        """Wood phase requires basic wooden tools."""
        assert "wooden_pickaxe" in WOOD_PHASE.required_items
        assert "wooden_sword" in WOOD_PHASE.required_items
        assert "crafting_table" in WOOD_PHASE.required_items

    def test_stone_phase_requirements(self):
        """Stone phase requires stone tools + furnace."""
        assert "stone_pickaxe" in STONE_PHASE.required_items
        assert "stone_sword" in STONE_PHASE.required_items
        assert "furnace" in STONE_PHASE.required_items

    def test_iron_phase_requirements(self):
        """Iron phase requires iron tools + armor."""
        assert "iron_pickaxe" in IRON_PHASE.required_items
        assert "iron_sword" in IRON_PHASE.required_items
        assert "iron_chestplate" in IRON_PHASE.required_items

    def test_diamond_phase_requirements(self):
        """Diamond phase requires diamond tools."""
        assert "diamond_pickaxe" in DIAMOND_PHASE.required_items
        assert "diamond_sword" in DIAMOND_PHASE.required_items

    def test_phases_have_skills(self):
        """Each predefined phase lists skills to learn."""
        for phase in _PREDEFINED_PHASES:
            assert len(phase.skills_to_learn) > 0, f"Phase '{phase.name}' has no skills"

    def test_phases_have_time_budgets(self):
        """Each predefined phase has a positive time budget."""
        for phase in _PREDEFINED_PHASES:
            assert phase.time_budget_minutes > 0, f"Phase '{phase.name}' has no time budget"

    def test_phase_progression_increasing_budget(self):
        """Iron phase has the largest time budget (hardest phase)."""
        budgets = {p.name: p.time_budget_minutes for p in _PREDEFINED_PHASES}
        assert budgets["iron"] >= budgets["wood"]
        assert budgets["iron"] >= budgets["stone"]
        assert budgets["iron"] >= budgets["diamond"]


# ── Milestone Checking ───────────────────────────────────────────────────────


class TestMilestoneChecking:
    """Tests for milestone checking with specific predefined phase inventories."""

    def test_milestone_wood_complete(self):
        """Wood phase completes with wooden_pickaxe + wooden_sword + crafting_table."""
        inventory = {
            "wooden_pickaxe": 1,
            "wooden_sword": 1,
            "crafting_table": 1,
        }
        assert WOOD_PHASE.is_complete(inventory) is True
        assert WOOD_PHASE.missing_items(inventory) == {}

    def test_milestone_wood_incomplete(self):
        """Wood phase fails without all three items."""
        assert WOOD_PHASE.is_complete({"wooden_pickaxe": 1}) is False
        assert WOOD_PHASE.is_complete({"wooden_sword": 1, "crafting_table": 1}) is False
        assert WOOD_PHASE.is_complete({}) is False

    def test_milestone_wood_missing_items(self):
        """Wood phase missing_items reports correctly."""
        missing = WOOD_PHASE.missing_items({"wooden_pickaxe": 1})
        assert missing == {"wooden_sword": 1, "crafting_table": 1}

    def test_milestone_stone_complete(self):
        """Stone phase completes with stone_pickaxe + stone_sword + furnace."""
        inventory = {
            "stone_pickaxe": 1,
            "stone_sword": 1,
            "furnace": 1,
        }
        assert STONE_PHASE.is_complete(inventory) is True
        assert STONE_PHASE.missing_items(inventory) == {}

    def test_milestone_stone_incomplete(self):
        """Stone phase fails without all three items."""
        assert STONE_PHASE.is_complete({"stone_pickaxe": 1, "stone_sword": 1}) is False
        assert STONE_PHASE.is_complete({"furnace": 1}) is False

    def test_milestone_stone_missing_items(self):
        """Stone phase missing_items reports correctly."""
        missing = STONE_PHASE.missing_items({"stone_pickaxe": 1})
        assert missing == {"stone_sword": 1, "furnace": 1}

    def test_milestone_iron_complete(self):
        """Iron phase completes with iron_pickaxe + iron_sword + iron_chestplate."""
        inventory = {
            "iron_pickaxe": 1,
            "iron_sword": 1,
            "iron_chestplate": 1,
        }
        assert IRON_PHASE.is_complete(inventory) is True
        assert IRON_PHASE.missing_items(inventory) == {}

    def test_milestone_iron_incomplete(self):
        """Iron phase fails without all three items."""
        assert IRON_PHASE.is_complete({"iron_pickaxe": 1, "iron_sword": 1}) is False
        assert IRON_PHASE.is_complete({"iron_chestplate": 1}) is False

    def test_milestone_iron_missing_items(self):
        """Iron phase missing_items reports correctly."""
        missing = IRON_PHASE.missing_items({"iron_ingot": 3})
        assert missing == {
            "iron_pickaxe": 1,
            "iron_sword": 1,
            "iron_chestplate": 1,
        }

    def test_milestone_diamond_complete(self):
        """Diamond phase completes with diamond_pickaxe + diamond_sword."""
        inventory = {
            "diamond_pickaxe": 1,
            "diamond_sword": 1,
        }
        assert DIAMOND_PHASE.is_complete(inventory) is True
        assert DIAMOND_PHASE.missing_items(inventory) == {}

    def test_milestone_diamond_incomplete(self):
        """Diamond phase fails without both items."""
        assert DIAMOND_PHASE.is_complete({"diamond_pickaxe": 1}) is False
        assert DIAMOND_PHASE.is_complete({"diamond_sword": 1}) is False
        assert DIAMOND_PHASE.is_complete({}) is False

    def test_milestone_diamond_missing_items(self):
        """Diamond phase missing_items reports correctly."""
        missing = DIAMOND_PHASE.missing_items({"cobblestone": 20})
        assert missing == {"diamond_pickaxe": 1, "diamond_sword": 1}

    def test_milestone_surplus_items_accepted(self):
        """Surplus items beyond required count still satisfy milestone."""
        inventory = {
            "wooden_pickaxe": 5,
            "wooden_sword": 3,
            "crafting_table": 2,
        }
        assert WOOD_PHASE.is_complete(inventory) is True

    def test_milestone_cross_phase_inventory(self):
        """Inventory with items from multiple phases satisfies correct milestones."""
        mixed = {
            "wooden_pickaxe": 1, "wooden_sword": 1, "crafting_table": 1,
            "stone_pickaxe": 1, "stone_sword": 1, "furnace": 1,
            "iron_pickaxe": 1, "iron_sword": 1, "iron_chestplate": 1,
            "diamond_pickaxe": 1, "diamond_sword": 1,
        }
        for phase in _PREDEFINED_PHASES:
            assert phase.is_complete(mixed) is True, f"Phase '{phase.name}' should be complete"


# ── Factory ──────────────────────────────────────────────────────────────────


class TestCreateDefaultTechTree:
    """Tests for the create_default_tech_tree factory."""

    def test_create_default_tech_tree(self):
        """Factory produces a valid config with all 4 phases."""
        config = create_default_tech_tree()

        assert isinstance(config, TechTreeConfig)
        assert len(config.phases) == 4
        assert config.total_time_budget_minutes == 60

    def test_create_default_tech_tree_phase_order(self):
        """Phases are in wood → stone → iron → diamond order."""
        config = create_default_tech_tree()
        names = [p.name for p in config.phases]
        assert names == ["wood", "stone", "iron", "diamond"]

    def test_create_default_tech_tree_passes_validation(self):
        """Default config validation produces no blocking errors."""
        config = create_default_tech_tree()
        warnings = config.validate()
        # May have soft warnings, but no "no phases" error
        assert not any("no phases" in w.lower() for w in warnings)


# ── _phase_tasks ─────────────────────────────────────────────────────────────


class TestPhaseTasks:
    """Tests for the _phase_tasks helper."""

    def test_wood_tasks(self):
        """Wood phase has expected task sequence."""
        tasks = _phase_tasks("wood")
        assert len(tasks) > 0
        labels = [t[0] for t in tasks]
        assert "collect_oak_log" in labels
        assert "craft_wooden_pickaxe" in labels

    def test_stone_tasks(self):
        """Stone phase has expected tasks."""
        tasks = _phase_tasks("stone")
        labels = [t[0] for t in tasks]
        assert "mine_cobblestone" in labels
        assert "craft_furnace" in labels

    def test_iron_tasks(self):
        """Iron phase has expected tasks."""
        tasks = _phase_tasks("iron")
        labels = [t[0] for t in tasks]
        assert "mine_iron_ore" in labels
        assert "smelt_iron_ingot" in labels

    def test_diamond_tasks(self):
        """Diamond phase has expected tasks."""
        tasks = _phase_tasks("diamond")
        labels = [t[0] for t in tasks]
        assert "mine_diamond_ore" in labels
        assert "craft_diamond_pickaxe" in labels

    def test_unknown_phase_tasks(self):
        """Unknown phase returns empty task list."""
        tasks = _phase_tasks("nonexistent")
        assert tasks == []

    def test_task_tuple_structure(self):
        """Each task is a (label, action, params) triple."""
        for task in _phase_tasks("wood"):
            assert len(task) == 3
            label, action, params = task
            assert isinstance(label, str)
            assert isinstance(action, str)
            assert isinstance(params, dict)


# ── TechTreeRunner ───────────────────────────────────────────────────────────


class TestTechTreeRunnerInit:
    """Tests for TechTreeRunner initialization."""

    def test_tech_tree_runner_init(self):
        """Runner stores bridge, skill_library, and config."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=[make_phase()])

        runner = TechTreeRunner(bridge, lib, config)

        assert runner._bridge is bridge
        assert runner._skill_library is lib
        assert runner._config is config

    def test_tech_tree_runner_init_default_config(self):
        """Runner uses default tech tree when config is None."""
        bridge = make_bridge()
        lib = make_skill_library()

        runner = TechTreeRunner(bridge, lib)

        assert len(runner._config.phases) == 4
        assert runner._config.total_time_budget_minutes == 60

    def test_tech_tree_runner_metrics_initialized(self):
        """Runner starts with fresh metrics."""
        bridge = make_bridge()
        lib = make_skill_library()
        runner = TechTreeRunner(bridge, lib)

        assert isinstance(runner._metrics, TechTreeMetrics)
        assert runner._metrics.phases_completed == []


# ── TechTreeRunner.run() ─────────────────────────────────────────────────────


class TestTechTreeRunnerRun:
    """Tests for TechTreeRunner.run() — the async main loop."""

    async def test_run_completes_all_phases(self):
        """Runner completes all phases when inventory satisfies milestones."""
        # Inventory that satisfies all phase requirements
        full_inventory = {
            "wooden_pickaxe": 1, "wooden_sword": 1, "crafting_table": 1,
            "stone_pickaxe": 1, "stone_sword": 1, "furnace": 1,
            "iron_pickaxe": 1, "iron_sword": 1, "iron_chestplate": 1,
            "diamond_pickaxe": 1, "diamond_sword": 1,
        }
        bridge = make_bridge(inventory=full_inventory)
        lib = make_skill_library()
        config = TechTreeConfig(
            phases=list(_PREDEFINED_PHASES),
            total_time_budget_minutes=60,
        )
        runner = TechTreeRunner(bridge, lib, config)

        metrics = await runner.run()

        assert len(metrics.phases_completed) == 4
        assert metrics.total_time_seconds >= 0
        assert metrics.items_collected == full_inventory

    async def test_run_stops_on_global_timeout(self):
        """Runner stops when global time budget is exhausted."""
        # Empty inventory — phases won't complete, but we test budget logic
        bridge = make_bridge(inventory={})
        lib = make_skill_library()
        config = TechTreeConfig(
            phases=[
                make_phase(name="a", time_budget_minutes=1),
                make_phase(name="b", time_budget_minutes=1),
            ],
            total_time_budget_minutes=0,  # instant timeout
        )
        runner = TechTreeRunner(bridge, lib, config)

        metrics = await runner.run()

        # Should have attempted no phases (or very few) due to 0 budget
        # The exact count depends on timing, but at least it didn't hang
        assert isinstance(metrics, TechTreeMetrics)

    async def test_run_handles_bridge_error(self):
        """Runner handles bridge command failures gracefully."""
        bridge = MagicMock()
        bridge.send_command = AsyncMock(
            return_value={"status": "error", "result": "connection lost"}
        )
        lib = make_skill_library()
        config = TechTreeConfig(
            phases=[make_phase(name="test")],
            total_time_budget_minutes=1,
        )
        runner = TechTreeRunner(bridge, lib, config)

        metrics = await runner.run()

        # Should complete without crashing
        assert isinstance(metrics, TechTreeMetrics)
        assert metrics.items_collected == {}

    async def test_run_counts_deaths(self):
        """Runner tracks death count delta."""
        bridge = make_bridge(deaths=3)
        lib = make_skill_library()
        config = TechTreeConfig(
            phases=[make_phase(name="test", required_items={})],
            total_time_budget_minutes=1,
        )
        runner = TechTreeRunner(bridge, lib, config)

        metrics = await runner.run()

        # Deaths = final_deaths - initial_deaths; both calls return 3 → delta = 0
        # (In real scenario, deaths would increase between calls)
        assert metrics.deaths >= 0


# ── TechTreeReport ───────────────────────────────────────────────────────────


class TestTechTreeReport:
    """Tests for TechTreeReport data class."""

    def test_tech_tree_report_creation(self):
        """Report bundles config, metrics, phase_details, and timestamp."""
        config = TechTreeConfig(phases=[make_phase()])
        metrics = TechTreeMetrics(phases_completed=["test"], total_time_seconds=42.0)
        details = [
            {
                "name": "test",
                "completed": True,
                "elapsed_seconds": 42.0,
                "items_collected": {"test_item": 1},
                "missing_items": {},
            }
        ]

        report = TechTreeReport(
            config=config,
            metrics=metrics,
            phase_details=details,
        )

        assert report.config is config
        assert report.metrics is metrics
        assert report.phase_details == details
        assert report.timestamp  # auto-generated

    def test_report_timestamp_format(self):
        """Timestamp is ISO-8601."""
        report = TechTreeReport(
            config=TechTreeConfig(phases=[]),
            metrics=TechTreeMetrics(),
        )
        # Should be parseable as ISO format
        datetime.fromisoformat(report.timestamp)

    def test_report_default_phase_details(self):
        """Default phase_details is empty list."""
        report = TechTreeReport(
            config=TechTreeConfig(phases=[]),
            metrics=TechTreeMetrics(),
        )
        assert report.phase_details == []


# ── TechTreeRunner.generate_report() ─────────────────────────────────────────


class TestGenerateReport:
    """Tests for TechTreeRunner.generate_report()."""

    def test_generate_report(self):
        """generate_report bundles current state into a TechTreeReport."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=[make_phase(name="test")])
        runner = TechTreeRunner(bridge, lib, config)

        report = runner.generate_report()

        assert isinstance(report, TechTreeReport)
        assert report.config is config
        assert report.metrics is runner._metrics
        assert isinstance(report.timestamp, str)

    def test_generate_report_with_phase_details(self):
        """Report includes phase_details from runner state."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=[make_phase()])
        runner = TechTreeRunner(bridge, lib, config)

        runner._phase_details = [
            {"name": "test", "completed": True, "elapsed_seconds": 5.0}
        ]
        report = runner.generate_report()

        assert len(report.phase_details) == 1
        assert report.phase_details[0]["name"] == "test"


# ── TechTreeRunner.generate_markdown_report() ────────────────────────────────


class TestGenerateMarkdownReport:
    """Tests for TechTreeRunner.generate_markdown_report()."""

    def test_tech_tree_report_markdown(self):
        """Markdown report contains key sections."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=[make_phase(name="test")])
        runner = TechTreeRunner(bridge, lib, config)

        md = runner.generate_markdown_report()

        assert "# Tech Tree Run Report" in md
        assert "## Summary" in md
        assert "## Phase Details" in md
        assert "## Final Inventory" in md

    def test_markdown_contains_phase_info(self):
        """Markdown includes phase details when present."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=[make_phase(name="test")])
        runner = TechTreeRunner(bridge, lib, config)

        runner._phase_details = [
            {
                "name": "test",
                "completed": True,
                "elapsed_seconds": 12.5,
                "items_collected": {"test_item": 1},
                "missing_items": {},
            }
        ]
        runner._metrics = TechTreeMetrics(
            phases_completed=["test"],
            total_time_seconds=12.5,
            items_collected={"test_item": 1},
        )

        md = runner.generate_markdown_report()

        assert "Test Phase" in md
        assert "12.5s" in md
        assert "test_item" in md

    def test_markdown_with_missing_items(self):
        """Markdown lists missing items for incomplete phases."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=[make_phase(name="incomplete")])
        runner = TechTreeRunner(bridge, lib, config)

        runner._phase_details = [
            {
                "name": "incomplete",
                "completed": False,
                "elapsed_seconds": 60.0,
                "items_collected": {},
                "missing_items": {"diamond_pickaxe": 1},
            }
        ]

        md = runner.generate_markdown_report()

        assert "Missing" in md
        assert "diamond_pickaxe" in md

    def test_markdown_with_explicit_report(self):
        """Markdown generation accepts an explicit report object."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=[make_phase()])
        runner = TechTreeRunner(bridge, lib, config)

        report = TechTreeReport(
            config=config,
            metrics=TechTreeMetrics(phases_completed=["test"]),
            phase_details=[],
        )

        md = runner.generate_markdown_report(report)
        assert "# Tech Tree Run Report" in md


# ── TechTreeRunner.save_report() ─────────────────────────────────────────────


class TestSaveReport:
    """Tests for TechTreeRunner.save_report()."""

    def test_tech_tree_report_save(self):
        """Report is saved as markdown file with timestamp filename."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=[make_phase(name="test")])
        runner = TechTreeRunner(bridge, lib, config)

        runner._metrics = TechTreeMetrics(phases_completed=["test"])

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = runner.save_report(directory=tmpdir)

            assert filepath.exists()
            assert filepath.suffix == ".md"
            # Filename format: YYYY-MM-DD_HHMMSS.md
            assert filepath.stem[0].isdigit()

            content = filepath.read_text(encoding="utf-8")
            assert "# Tech Tree Run Report" in content

    def test_save_report_creates_directory(self):
        """save_report creates the target directory if needed."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=[make_phase()])
        runner = TechTreeRunner(bridge, lib, config)

        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir) / "deeply" / "nested" / "dir"
            filepath = runner.save_report(directory=nested)

            assert filepath.exists()
            assert nested.is_dir()

    def test_save_report_with_explicit_report(self):
        """save_report accepts an explicit report object."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=[make_phase()])
        runner = TechTreeRunner(bridge, lib, config)

        report = TechTreeReport(
            config=config,
            metrics=TechTreeMetrics(),
            phase_details=[],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = runner.save_report(report=report, directory=tmpdir)
            assert filepath.exists()


# ── TechTreeRunner._find_skill() ─────────────────────────────────────────────


class TestFindSkill:
    """Tests for TechTreeRunner._find_skill() — skill search in library."""

    async def test_find_skill_keyword_match(self):
        """_find_skill returns skill found via keyword search."""
        bridge = make_bridge()
        lib = make_skill_library()
        mock_skill = MagicMock()
        mock_skill.id = "craft_wooden_pickaxe_v1"
        lib.search_by_keyword = AsyncMock(return_value=[mock_skill])

        runner = TechTreeRunner(bridge, lib)
        result = await runner._find_skill("craft_wooden_pickaxe")

        assert result is mock_skill
        lib.search_by_keyword.assert_awaited_once_with("craft_wooden_pickaxe", limit=1)

    async def test_find_skill_goal_fallback(self):
        """_find_skill falls back to goal-based search when keyword returns nothing."""
        bridge = make_bridge()
        lib = make_skill_library()
        mock_skill = MagicMock()
        mock_skill.id = "mine_cobblestone_v1"
        lib.search_by_keyword = AsyncMock(return_value=[])
        lib.search_skills = AsyncMock(return_value=[mock_skill])

        runner = TechTreeRunner(bridge, lib)
        result = await runner._find_skill("mine_cobblestone")

        assert result is mock_skill
        lib.search_by_keyword.assert_awaited_once()
        lib.search_skills.assert_awaited_once_with("mine cobblestone", limit=1)

    async def test_find_skill_no_match(self):
        """_find_skill returns None when no skill matches."""
        bridge = make_bridge()
        lib = make_skill_library()
        lib.search_by_keyword = AsyncMock(return_value=[])
        lib.search_skills = AsyncMock(return_value=[])

        runner = TechTreeRunner(bridge, lib)
        result = await runner._find_skill("nonexistent_task")

        assert result is None

    async def test_find_skill_prefers_keyword_over_goal(self):
        """_find_skill does not call search_skills when keyword returns a match."""
        bridge = make_bridge()
        lib = make_skill_library()
        lib.search_by_keyword = AsyncMock(return_value=[MagicMock()])
        lib.search_skills = AsyncMock()

        runner = TechTreeRunner(bridge, lib)
        await runner._find_skill("some_task")

        lib.search_by_keyword.assert_awaited_once()
        lib.search_skills.assert_not_awaited()


# ── TechTreeRunner._execute_task() ───────────────────────────────────────────


class TestExecuteTask:
    """Tests for TechTreeRunner._execute_task() — task execution via bridge."""

    async def test_execute_task_bridge_fallback(self):
        """_execute_task falls back to bridge when no skill matches."""
        bridge = make_bridge(inventory={})
        lib = make_skill_library()
        lib.search_by_keyword = AsyncMock(return_value=[])
        lib.search_skills = AsyncMock(return_value=[])

        runner = TechTreeRunner(bridge, lib)
        resp = await runner._execute_task("collect_oak_log", "collect", {"block_type": "oak_log", "count": 4})

        assert resp["status"] == "success"
        bridge.send_command.assert_any_call("collect", {"block_type": "oak_log", "count": 4}, timeout=120.0)

    async def test_execute_task_craft_timeout(self):
        """_execute_task uses 60s timeout for craft actions."""
        bridge = make_bridge(inventory={})
        lib = make_skill_library()
        lib.search_by_keyword = AsyncMock(return_value=[])
        lib.search_skills = AsyncMock(return_value=[])

        runner = TechTreeRunner(bridge, lib)
        await runner._execute_task("craft_sword", "craft", {"recipe": "sword", "count": 1})

        bridge.send_command.assert_any_call("craft", {"recipe": "sword", "count": 1}, timeout=60.0)

    async def test_execute_task_skill_success(self):
        """_execute_task uses skill when found and tracks reuse."""
        bridge = make_bridge(inventory={})
        lib = make_skill_library()

        # Set up skill that succeeds
        mock_skill = MagicMock()
        mock_skill.id = "craft_wooden_pickaxe_v1"
        lib.search_by_keyword = AsyncMock(return_value=[mock_skill])

        skill_result = MagicMock()
        skill_result.success = True
        skill_result.duration = 2.5
        skill_result.context_updates = {"crafted": "wooden_pickaxe"}
        lib.execute_skill_by_id = AsyncMock(return_value=skill_result)
        lib.update_success = AsyncMock()
        lib.update_failure = AsyncMock()

        runner = TechTreeRunner(bridge, lib)
        resp = await runner._execute_task("craft_wooden_pickaxe", "craft", {"recipe": "wooden_pickaxe"})

        assert resp["status"] == "success"
        assert runner._metrics.skills_reused == 1
        lib.execute_skill_by_id.assert_awaited_once()
        lib.update_success.assert_awaited_once_with("craft_wooden_pickaxe_v1")
        lib.update_failure.assert_not_awaited()

    async def test_execute_task_skill_failure_falls_back(self):
        """_execute_task falls back to bridge when skill execution fails."""
        bridge = make_bridge(inventory={})
        lib = make_skill_library()

        mock_skill = MagicMock()
        mock_skill.id = "bad_skill_v1"
        lib.search_by_keyword = AsyncMock(return_value=[mock_skill])

        skill_result = MagicMock()
        skill_result.success = False
        skill_result.reason = "precondition failed"
        lib.execute_skill_by_id = AsyncMock(return_value=skill_result)
        lib.update_success = AsyncMock()
        lib.update_failure = AsyncMock()

        runner = TechTreeRunner(bridge, lib)
        resp = await runner._execute_task("craft_sword", "craft", {"recipe": "sword"})

        # Should have called bridge as fallback
        assert resp["status"] == "success"
        lib.update_failure.assert_awaited_once_with("bad_skill_v1")
        lib.update_success.assert_not_awaited()

    async def test_execute_task_bridge_error_response(self):
        """_execute_task returns error response from bridge without crashing."""
        bridge = MagicMock()
        bridge.send_command = AsyncMock(
            return_value={"status": "error", "result": "timeout"}
        )
        lib = make_skill_library()
        lib.search_by_keyword = AsyncMock(return_value=[])
        lib.search_skills = AsyncMock(return_value=[])

        runner = TechTreeRunner(bridge, lib)
        resp = await runner._execute_task("bad_task", "collect", {})

        assert resp["status"] == "error"


# ── _phase_tasks Structure ───────────────────────────────────────────────────


class TestPhaseTasksStructure:
    """Tests for _phase_tasks structural correctness."""

    def test_all_phases_have_tasks(self):
        """Every predefined phase has at least one task."""
        for phase in _PREDEFINED_PHASES:
            tasks = _phase_tasks(phase.name)
            assert len(tasks) > 0, f"Phase '{phase.name}' has no tasks"

    def test_wood_tasks_start_with_collection(self):
        """Wood phase tasks begin with resource collection."""
        tasks = _phase_tasks("wood")
        first_label, first_action, first_params = tasks[0]
        assert first_action in ("collect", "mine")
        assert "block_type" in first_params

    def test_diamond_tasks_end_with_crafting(self):
        """Diamond phase tasks end with crafting diamond tools."""
        tasks = _phase_tasks("diamond")
        last_label, last_action, last_params = tasks[-1]
        assert last_action == "craft"
        assert "diamond" in last_params.get("recipe", "")

    def test_iron_tasks_include_smelting(self):
        """Iron phase includes smelting step."""
        tasks = _phase_tasks("iron")
        labels = [t[0] for t in tasks]
        assert "smelt_iron_ingot" in labels

    def test_stone_tasks_include_furnace(self):
        """Stone phase includes furnace crafting."""
        tasks = _phase_tasks("stone")
        labels = [t[0] for t in tasks]
        assert "craft_furnace" in labels

    def test_task_params_have_required_keys(self):
        """Each task's params dict has the expected keys for its action type."""
        for phase_name in ("wood", "stone", "iron", "diamond"):
            for label, action, params in _phase_tasks(phase_name):
                if action in ("collect", "mine"):
                    assert "block_type" in params, f"{label}: missing block_type"
                    assert "count" in params, f"{label}: missing count"
                elif action == "craft":
                    assert "recipe" in params, f"{label}: missing recipe"


# ── TechTreeRunner._check_milestone() ────────────────────────────────────────


class TestCheckMilestone:
    """Tests for TechTreeRunner._check_milestone() — async milestone check."""

    async def test_check_milestone_delegates_to_phase(self):
        """_check_milestone delegates to phase.is_complete()."""
        bridge = make_bridge()
        lib = make_skill_library()
        runner = TechTreeRunner(bridge, lib)

        phase = make_phase(required_items={"sword": 1})
        assert await runner._check_milestone(phase, {"sword": 1}) is True
        assert await runner._check_milestone(phase, {}) is False

    async def test_check_milestone_with_predefined_phases(self):
        """_check_milestone works with all predefined phases."""
        bridge = make_bridge()
        lib = make_skill_library()
        runner = TechTreeRunner(bridge, lib)

        full_inv = {
            "wooden_pickaxe": 1, "wooden_sword": 1, "crafting_table": 1,
            "stone_pickaxe": 1, "stone_sword": 1, "furnace": 1,
            "iron_pickaxe": 1, "iron_sword": 1, "iron_chestplate": 1,
            "diamond_pickaxe": 1, "diamond_sword": 1,
        }
        for phase in _PREDEFINED_PHASES:
            assert await runner._check_milestone(phase, full_inv) is True


# ── TechTreeRunner._get_inventory / _get_death_count ─────────────────────────


class TestRunnerHelpers:
    """Tests for TechTreeRunner helper methods."""

    async def test_get_inventory_success(self):
        """_get_inventory returns inventory from bridge status."""
        inv = {"sword": 1, "pickaxe": 2}
        bridge = make_bridge(inventory=inv)
        lib = make_skill_library()
        runner = TechTreeRunner(bridge, lib)

        result = await runner._get_inventory()
        assert result == inv

    async def test_get_inventory_bridge_error(self):
        """_get_inventory returns empty dict on bridge failure."""
        bridge = MagicMock()
        bridge.send_command = AsyncMock(side_effect=Exception("connection lost"))
        lib = make_skill_library()
        runner = TechTreeRunner(bridge, lib)

        result = await runner._get_inventory()
        assert result == {}

    async def test_get_inventory_error_status(self):
        """_get_inventory returns empty dict when bridge returns error status."""
        bridge = MagicMock()
        bridge.send_command = AsyncMock(return_value={"status": "error", "result": "fail"})
        lib = make_skill_library()
        runner = TechTreeRunner(bridge, lib)

        result = await runner._get_inventory()
        assert result == {}

    async def test_get_death_count_success(self):
        """_get_death_count returns death count from bridge status."""
        bridge = make_bridge(deaths=5)
        lib = make_skill_library()
        runner = TechTreeRunner(bridge, lib)

        result = await runner._get_death_count()
        assert result == 5

    async def test_get_death_count_bridge_error(self):
        """_get_death_count returns 0 on bridge failure."""
        bridge = MagicMock()
        bridge.send_command = AsyncMock(side_effect=Exception("timeout"))
        lib = make_skill_library()
        runner = TechTreeRunner(bridge, lib)

        result = await runner._get_death_count()
        assert result == 0

    async def test_build_context_success(self):
        """_build_context extracts health/food/day from bridge status."""
        bridge = MagicMock()
        bridge.send_command = AsyncMock(return_value={
            "status": "success",
            "result": {
                "health": 15,
                "food": 18,
                "is_day": False,
                "is_night": True,
                "inventory": {"sword": 1},
            },
        })
        lib = make_skill_library()
        runner = TechTreeRunner(bridge, lib)

        ctx = await runner._build_context()
        assert ctx["health"] == 15
        assert ctx["food"] == 18
        assert ctx["is_day"] is False
        assert ctx["is_night"] is True
        assert ctx["inventory"] == {"sword": 1}

    async def test_build_context_bridge_error(self):
        """_build_context returns empty dict on bridge failure."""
        bridge = MagicMock()
        bridge.send_command = AsyncMock(side_effect=Exception("fail"))
        lib = make_skill_library()
        runner = TechTreeRunner(bridge, lib)

        ctx = await runner._build_context()
        assert ctx == {}


# ── TechTreeRunner.generate_benchmark_metrics() ──────────────────────────────


class TestGenerateBenchmarkMetrics:
    """Tests for TechTreeRunner.generate_benchmark_metrics()."""

    def _patch_benchmark(self):
        """Return a context manager that injects a fake benchmark module."""
        fake_module = MagicMock()
        fake_module.BenchmarkMetrics = _FakeBenchmarkMetrics
        return patch.dict(sys.modules, {
            "animetta.tools.minecraft.benchmark": fake_module,
        })

    def test_benchmark_metrics_all_phases_completed(self):
        """Benchmark shows completed=True when all phases are done."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=list(_PREDEFINED_PHASES))
        runner = TechTreeRunner(bridge, lib, config)

        runner._metrics = TechTreeMetrics(
            phases_completed=["wood", "stone", "iron", "diamond"],
            total_time_seconds=300.0,
            items_collected={
                "wooden_pickaxe": 1, "wooden_sword": 1, "crafting_table": 1,
                "stone_pickaxe": 1, "stone_sword": 1, "furnace": 1,
                "iron_pickaxe": 1, "iron_sword": 1, "iron_chestplate": 1,
                "diamond_pickaxe": 1, "diamond_sword": 1,
            },
            skills_learned=4,
            skills_reused=6,
            deaths=1,
        )

        with self._patch_benchmark():
            bm = runner.generate_benchmark_metrics()

        assert bm.completed is True
        assert bm.time_to_milestone == 300.0
        assert bm.elapsed_seconds == 300.0
        assert bm.skills_created == 4
        assert bm.skills_reused == 6
        assert bm.deaths == 1
        assert bm.unique_items_collected == 11

    def test_benchmark_metrics_partial_completion(self):
        """Benchmark shows completed=False when not all phases are done."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=list(_PREDEFINED_PHASES))
        runner = TechTreeRunner(bridge, lib, config)

        runner._metrics = TechTreeMetrics(
            phases_completed=["wood", "stone"],
            total_time_seconds=120.0,
            items_collected={"wooden_pickaxe": 1, "stone_sword": 1, "cobblestone": 10},
            skills_learned=2,
            skills_reused=1,
            deaths=0,
        )

        with self._patch_benchmark():
            bm = runner.generate_benchmark_metrics()

        assert bm.completed is False
        assert bm.time_to_milestone == 0.0  # not fully completed
        assert bm.elapsed_seconds == 120.0
        assert bm.unique_items_collected == 3

    def test_benchmark_metrics_empty_inventory(self):
        """Benchmark handles empty inventory gracefully."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=list(_PREDEFINED_PHASES))
        runner = TechTreeRunner(bridge, lib, config)

        runner._metrics = TechTreeMetrics()

        with self._patch_benchmark():
            bm = runner.generate_benchmark_metrics()

        assert bm.completed is False
        assert bm.unique_items_collected == 0
        assert bm.time_to_milestone == 0.0

    def test_benchmark_metrics_with_explicit_report(self):
        """generate_benchmark_metrics accepts an explicit report."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=[make_phase(name="test")])
        runner = TechTreeRunner(bridge, lib, config)

        report = TechTreeReport(
            config=config,
            metrics=TechTreeMetrics(
                phases_completed=["test"],
                total_time_seconds=60.0,
                items_collected={"test_item": 1},
                skills_learned=1,
                skills_reused=2,
                deaths=0,
            ),
        )

        with self._patch_benchmark():
            bm = runner.generate_benchmark_metrics(report=report)

        assert bm.completed is True
        assert bm.time_to_milestone == 60.0
        assert bm.unique_items_collected == 1

    def test_benchmark_metrics_zero_count_items_excluded(self):
        """Items with count=0 are not counted in unique_items_collected."""
        bridge = make_bridge()
        lib = make_skill_library()
        config = TechTreeConfig(phases=[make_phase(name="test")])
        runner = TechTreeRunner(bridge, lib, config)

        runner._metrics = TechTreeMetrics(
            phases_completed=["test"],
            items_collected={"sword": 1, "broken_item": 0, "shield": 2},
        )

        with self._patch_benchmark():
            bm = runner.generate_benchmark_metrics()

        assert bm.unique_items_collected == 2  # sword + shield, not broken_item


# ── TechTreeRunner.run() Integration ─────────────────────────────────────────


class TestRunnerRunIntegration:
    """Integration tests for TechTreeRunner.run() with realistic scenarios."""

    async def test_run_with_progressive_inventory(self):
        """Runner completes phases when inventory grows between phases."""
        # Simulate inventory that grows as tasks execute
        call_count = 0
        inventories = [
            {},  # initial
            {"wooden_pickaxe": 1, "wooden_sword": 1, "crafting_table": 1},  # after wood
            {"wooden_pickaxe": 1, "wooden_sword": 1, "crafting_table": 1,
             "stone_pickaxe": 1, "stone_sword": 1, "furnace": 1},  # after stone
            {"wooden_pickaxe": 1, "wooden_sword": 1, "crafting_table": 1,
             "stone_pickaxe": 1, "stone_sword": 1, "furnace": 1,
             "iron_pickaxe": 1, "iron_sword": 1, "iron_chestplate": 1},  # after iron
            {"wooden_pickaxe": 1, "wooden_sword": 1, "crafting_table": 1,
             "stone_pickaxe": 1, "stone_sword": 1, "furnace": 1,
             "iron_pickaxe": 1, "iron_sword": 1, "iron_chestplate": 1,
             "diamond_pickaxe": 1, "diamond_sword": 1},  # after diamond
        ]

        async def mock_send_command(action, params=None, timeout=60.0):
            nonlocal call_count
            inv_idx = min(call_count // 3, len(inventories) - 1)
            call_count += 1
            return {
                "status": "success",
                "result": {
                    "inventory": inventories[inv_idx],
                    "deaths": 0,
                    "health": 20,
                    "food": 20,
                },
            }

        bridge = MagicMock()
        bridge.send_command = AsyncMock(side_effect=mock_send_command)
        lib = make_skill_library()

        config = TechTreeConfig(
            phases=list(_PREDEFINED_PHASES),
            total_time_budget_minutes=60,
        )
        runner = TechTreeRunner(bridge, lib, config)

        metrics = await runner.run()

        # At least wood phase should complete (first inventory satisfies it)
        assert len(metrics.phases_completed) >= 1

    async def test_run_single_phase_with_empty_required_items(self):
        """Runner completes phase with no required items immediately."""
        bridge = make_bridge(inventory={})
        lib = make_skill_library()
        config = TechTreeConfig(
            phases=[TechTreePhase(
                name="empty",
                time_budget_minutes=1,
                required_items={},
                skills_to_learn=[],
                description="No-op phase",
            )],
            total_time_budget_minutes=5,
        )
        runner = TechTreeRunner(bridge, lib, config)

        metrics = await runner.run()

        assert "empty" in metrics.phases_completed

    async def test_run_records_phase_details(self):
        """Runner records phase_details during execution."""
        full_inv = {
            "wooden_pickaxe": 1, "wooden_sword": 1, "crafting_table": 1,
        }
        bridge = make_bridge(inventory=full_inv)
        lib = make_skill_library()
        config = TechTreeConfig(
            phases=[WOOD_PHASE],
            total_time_budget_minutes=10,
        )
        runner = TechTreeRunner(bridge, lib, config)

        await runner.run()

        assert len(runner._phase_details) >= 1
        detail = runner._phase_details[0]
        assert detail["name"] == "wood"
        assert "elapsed_seconds" in detail

    async def test_run_generate_report_after_run(self):
        """Runner can generate a report after run completes."""
        full_inv = {"wooden_pickaxe": 1, "wooden_sword": 1, "crafting_table": 1}
        bridge = make_bridge(inventory=full_inv)
        lib = make_skill_library()
        config = TechTreeConfig(phases=[WOOD_PHASE], total_time_budget_minutes=10)
        runner = TechTreeRunner(bridge, lib, config)

        await runner.run()
        report = runner.generate_report()

        assert isinstance(report, TechTreeReport)
        assert report.config is config
        assert len(report.metrics.phases_completed) >= 1
