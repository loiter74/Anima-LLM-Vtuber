"""Tests for BenchmarkRunner — benchmark configurations, scenarios, and metrics."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from animetta.tools.minecraft.benchmark.criteria import (
    _check_building_criteria,
    _check_learning_criteria,
    _check_survival_criteria,
    _count_unique_items,
    _l1_distance,
)
from animetta.tools.minecraft.benchmark.main import (
    ALL_CONFIGS,
    ALL_SCENARIOS,
    BUILDING_CHALLENGE,
    LEARNING_CHALLENGE,
    SURVIVAL_CHALLENGE,
    BenchmarkConfig,
    BenchmarkMetrics,
    BenchmarkMode,
    BenchmarkRunner,
    BenchmarkScenario,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_bridge() -> MagicMock:
    """Create a mock MinecraftBridge with async send_command."""
    bridge = MagicMock()
    bridge.send_command = AsyncMock(
        return_value={
            "status": "success",
            "result": {
                "x": 0, "y": 64, "z": 0,
                "health": 20, "food": 20,
                "inventory": {},
            },
        }
    )
    return bridge


def make_skill_library() -> MagicMock:
    """Create a mock SkillLibrary."""
    lib = MagicMock()
    lib.save_skill = AsyncMock(return_value=True)
    lib.get_all_skills = AsyncMock(return_value=[])
    lib.get_learned_skills = AsyncMock(return_value=[])
    return lib


def make_skill(skill_id: str = "test_skill", is_learned: bool = False) -> MagicMock:
    """Create a mock Skill."""
    skill = MagicMock()
    skill.id = skill_id
    skill.name = f"Skill {skill_id}"
    skill.is_learned = is_learned
    return skill


# ── BenchmarkConfig ───────────────────────────────────────────────────────────

class TestBenchmarkConfig:
    """BenchmarkConfig dataclass tests."""

    def test_benchmark_config_creation(self):
        """Config creation with minimal args — defaults applied."""
        cfg = BenchmarkConfig(name="Test", mode=BenchmarkMode.RULE_ONLY)
        assert cfg.name == "Test"
        assert cfg.mode == BenchmarkMode.RULE_ONLY
        assert cfg.world_seed is None
        assert cfg.time_limit_minutes == 20

    def test_benchmark_config_with_seed(self):
        """Config creation with explicit world seed."""
        cfg = BenchmarkConfig(
            name="Seeded",
            mode=BenchmarkMode.LLM_ONLY,
            world_seed="12345",
            time_limit_minutes=10,
        )
        assert cfg.world_seed == "12345"
        assert cfg.time_limit_minutes == 10

    def test_benchmark_config_modes(self):
        """All 4 benchmark modes are accessible and distinct."""
        modes = [
            BenchmarkMode.RULE_ONLY,
            BenchmarkMode.LLM_ONLY,
            BenchmarkMode.PREDEFINED,
            BenchmarkMode.FULL_VOYAGER,
        ]
        assert len(modes) == 4
        # Values are unique
        values = [m.value for m in modes]
        assert len(set(values)) == 4
        # String enum behavior
        assert BenchmarkMode.RULE_ONLY == "rule-only"
        assert BenchmarkMode.FULL_VOYAGER == "full-voyager"

    def test_all_configs_list(self):
        """ALL_CONFIGS has one entry per mode."""
        assert len(ALL_CONFIGS) == 4
        modes = {c.mode for c in ALL_CONFIGS}
        assert modes == {
            BenchmarkMode.RULE_ONLY,
            BenchmarkMode.LLM_ONLY,
            BenchmarkMode.PREDEFINED,
            BenchmarkMode.FULL_VOYAGER,
        }


# ── BenchmarkScenario ─────────────────────────────────────────────────────────

class TestBenchmarkScenario:
    """BenchmarkScenario dataclass tests."""

    def test_scenario_definitions(self):
        """4 predefined scenarios exist in ALL_SCENARIOS."""
        assert len(ALL_SCENARIOS) == 4
        names = {s.name for s in ALL_SCENARIOS}
        assert names == {
            "Survival Challenge",
            "Building Challenge",
            "Learning Challenge",
            "Tech Tree Unlock",
        }

    def test_survival_challenge_criteria(self):
        """Survival challenge requires iron_pickaxe + iron_sword, 0 deaths."""
        assert SURVIVAL_CHALLENGE.name == "Survival Challenge"
        assert SURVIVAL_CHALLENGE.time_limit_minutes == 20
        criteria = SURVIVAL_CHALLENGE.success_criteria
        assert "iron_pickaxe" in criteria["required_items"]
        assert "iron_sword" in criteria["required_items"]
        assert criteria["max_deaths"] == 0

    def test_building_challenge_criteria(self):
        """Building challenge requires minimum enclosed volume."""
        assert BUILDING_CHALLENGE.name == "Building Challenge"
        assert BUILDING_CHALLENGE.time_limit_minutes == 25
        criteria = BUILDING_CHALLENGE.success_criteria
        assert criteria["min_enclosed_volume"] == 75
        assert criteria["min_dimensions"] == (5, 5, 3)

    def test_learning_challenge_criteria(self):
        """Learning challenge requires minimum tasks and skills."""
        assert LEARNING_CHALLENGE.name == "Learning Challenge"
        assert LEARNING_CHALLENGE.time_limit_minutes == 15
        criteria = LEARNING_CHALLENGE.success_criteria
        assert criteria["min_tasks_completed"] == 5
        assert criteria["min_skills_learned"] == 2


# ── BenchmarkMetrics ──────────────────────────────────────────────────────────

class TestBenchmarkMetrics:
    """BenchmarkMetrics dataclass tests."""

    def test_metrics_defaults(self):
        """Default BenchmarkMetrics has zero/empty values."""
        m = BenchmarkMetrics()
        assert m.time_to_milestone == 0.0
        assert m.unique_items_collected == 0
        assert m.distance_traveled == 0.0
        assert m.skills_created == 0
        assert m.skills_reused == 0
        assert m.task_success_rate == 0.0
        assert m.deaths == 0
        assert m.final_inventory == {}
        assert m.completed is False
        assert m.elapsed_seconds == 0.0
        assert m.tasks_attempted == 0
        assert m.tasks_succeeded == 0

    def test_metrics_with_values(self):
        """BenchmarkMetrics accepts explicit values."""
        m = BenchmarkMetrics(
            time_to_milestone=120.5,
            unique_items_collected=5,
            distance_traveled=500.0,
            skills_created=2,
            deaths=1,
            completed=True,
            elapsed_seconds=300.0,
            tasks_attempted=10,
            tasks_succeeded=8,
        )
        assert m.time_to_milestone == 120.5
        assert m.unique_items_collected == 5
        assert m.completed is True
        assert m.tasks_succeeded == 8

    def test_metrics_serialization(self):
        """BenchmarkMetrics fields are accessible (dataclass behavior)."""
        m = BenchmarkMetrics(
            deaths=3,
            final_inventory={"cobblestone": 10, "oak_planks": 5},
            task_success_rate=0.75,
        )
        # Verify dataclass fields work as expected
        assert m.deaths == 3
        assert m.final_inventory["cobblestone"] == 10
        assert m.task_success_rate == 0.75
        # Test dataclass equality
        m2 = BenchmarkMetrics(deaths=3, task_success_rate=0.75)
        assert m.deaths == m2.deaths
        assert m.task_success_rate == m2.task_success_rate


# ── Helper Functions ──────────────────────────────────────────────────────────

class TestHelperFunctions:
    """Tests for module-level helper functions."""

    def test_l1_distance_same_point(self):
        """L1 distance between identical points is zero."""
        assert _l1_distance((0, 0, 0), (0, 0, 0)) == 0.0

    def test_l1_distance_simple(self):
        """L1 distance sums absolute differences."""
        assert _l1_distance((0, 0, 0), (3, 4, 5)) == 12.0

    def test_l1_distance_negative(self):
        """L1 distance handles negative coordinates."""
        assert _l1_distance((-1, -1, -1), (1, 1, 1)) == 6.0

    def test_count_unique_items_empty(self):
        """Empty inventory has 0 unique items."""
        assert _count_unique_items({}) == 0

    def test_count_unique_items_basic(self):
        """Counts items with count > 0."""
        inv = {"sword": 1, "dirt": 64, "air": 0}
        assert _count_unique_items(inv) == 2

    def test_count_unique_items_all_zero(self):
        """All-zero inventory has 0 unique items."""
        assert _count_unique_items({"a": 0, "b": 0}) == 0

    def test_check_survival_criteria_met(self):
        """Survival criteria met when required items present and no deaths."""
        m = BenchmarkMetrics(deaths=0)
        inv = {"iron_pickaxe": 1, "iron_sword": 1}
        criteria = SURVIVAL_CHALLENGE.success_criteria
        assert _check_survival_criteria(m, criteria, inv) is True

    def test_check_survival_criteria_missing_items(self):
        """Survival criteria fails when items are missing."""
        m = BenchmarkMetrics(deaths=0)
        inv = {"iron_pickaxe": 1}
        criteria = SURVIVAL_CHALLENGE.success_criteria
        assert _check_survival_criteria(m, criteria, inv) is False

    def test_check_survival_criteria_deaths(self):
        """Survival criteria fails when deaths exceed max_deaths."""
        m = BenchmarkMetrics(deaths=1)
        inv = {"iron_pickaxe": 1, "iron_sword": 1}
        criteria = SURVIVAL_CHALLENGE.success_criteria
        assert _check_survival_criteria(m, criteria, inv) is False

    def test_check_learning_criteria_met(self):
        """Learning criteria met when tasks and skills thresholds passed."""
        m = BenchmarkMetrics(tasks_succeeded=5, skills_created=2)
        criteria = LEARNING_CHALLENGE.success_criteria
        assert _check_learning_criteria(m, criteria) is True

    def test_check_learning_criteria_insufficient_tasks(self):
        """Learning criteria fails with too few tasks."""
        m = BenchmarkMetrics(tasks_succeeded=4, skills_created=2)
        criteria = LEARNING_CHALLENGE.success_criteria
        assert _check_learning_criteria(m, criteria) is False

    def test_check_learning_criteria_insufficient_skills(self):
        """Learning criteria fails with too few skills."""
        m = BenchmarkMetrics(tasks_succeeded=5, skills_created=1)
        criteria = LEARNING_CHALLENGE.success_criteria
        assert _check_learning_criteria(m, criteria) is False

    def test_check_building_criteria_with_placed_blocks(self):
        """Building criteria met when enough blocks placed."""
        m = BenchmarkMetrics()
        criteria = BUILDING_CHALLENGE.success_criteria
        bridge_status = {"blocks_placed": 80}
        assert _check_building_criteria(m, criteria, bridge_status) is True

    def test_check_building_criteria_insufficient_blocks(self):
        """Building criteria fails when not enough blocks placed."""
        m = BenchmarkMetrics()
        criteria = BUILDING_CHALLENGE.success_criteria
        bridge_status = {"blocks_placed": 50}
        assert _check_building_criteria(m, criteria, bridge_status) is False


# ── BenchmarkRunner ───────────────────────────────────────────────────────────

class TestBenchmarkRunner:
    """BenchmarkRunner initialization and lifecycle tests."""

    def test_runner_initialization(self):
        """BenchmarkRunner initializes with default skill library when none given."""
        bridge = make_bridge()
        runner = BenchmarkRunner(bridge=bridge)

        assert runner._bridge is bridge
        assert runner._llm_service is None
        assert runner._rules_engine is None
        # Default SkillLibrary is created
        assert runner._skill_library is not None
        assert runner._predefined_skills == []

    def test_runner_initialization_with_all_deps(self):
        """BenchmarkRunner accepts all optional dependencies."""
        bridge = make_bridge()
        llm = MagicMock()
        skill_lib = make_skill_library()
        rules = MagicMock()

        runner = BenchmarkRunner(
            bridge=bridge,
            llm_service=llm,
            skill_library=skill_lib,
            rules_engine=rules,
        )
        assert runner._bridge is bridge
        assert runner._llm_service is llm
        assert runner._skill_library is skill_lib
        assert runner._rules_engine is rules

    def test_runner_snapshot_interval(self):
        """Runner has a snapshot interval constant."""
        assert BenchmarkRunner._SNAPSHOT_INTERVAL == 5.0

    async def test_runner_load_predefined_skills_import_error(self):
        """load_predefined_skills handles ImportError gracefully."""
        bridge = make_bridge()
        runner = BenchmarkRunner(bridge=bridge)

        with (
            patch("animetta.tools.minecraft.benchmark.runner.AutonomousLoop"),
            # Force ImportError by patching the import itself
            patch.dict("sys.modules", {"animetta.tools.minecraft.skill.predefined": None}),
        ):
            await runner.load_predefined_skills()
            # Should remain empty when import fails
            assert runner._predefined_skills == []

    async def test_runner_load_predefined_skills_success(self):
        """load_predefined_skills loads skills when module exists."""
        bridge = make_bridge()
        runner = BenchmarkRunner(bridge=bridge)

        fake_skills = [make_skill("skill_1"), make_skill("skill_2")]
        with patch(
            "animetta.tools.minecraft.benchmark.runner.AutonomousLoop"
        ), patch(
            "animetta.tools.minecraft.skill.predefined.get_predefined_skills",
            return_value=fake_skills,
        ):
            await runner.load_predefined_skills()
            assert len(runner._predefined_skills) == 2


class TestBenchmarkRunnerScenario:
    """Test BenchmarkRunner.run_scenario with mocked dependencies."""

    async def test_runner_scenario_with_mock_rule_only(self):
        """Run a scenario in RULE_ONLY mode with mocked bridge and loop."""
        bridge = make_bridge()
        skill_lib = make_skill_library()

        runner = BenchmarkRunner(bridge=bridge, skill_library=skill_lib)

        scenario = BenchmarkScenario(
            name="Test Scenario",
            description="A test scenario",
            success_criteria={"min_tasks_completed": 0, "min_skills_learned": 0},
            time_limit_minutes=0,  # Will be overridden to minimum
        )
        config = BenchmarkConfig(
            name="Test Config",
            mode=BenchmarkMode.RULE_ONLY,
            time_limit_minutes=0,
        )

        # Mock AutonomousLoop to avoid real async loop
        mock_loop = MagicMock()
        mock_loop.start = AsyncMock()
        mock_loop.stop = AsyncMock()

        # Make bridge.send_command return world-state-like responses
        bridge.send_command = AsyncMock(
            return_value={
                "status": "success",
                "result": {
                    "x": 10, "y": 64, "z": 20,
                    "health": 20, "food": 20,
                    "inventory": {"cobblestone": 5},
                },
            }
        )

        with patch(
            "animetta.tools.minecraft.benchmark.runner.AutonomousLoop",
            return_value=mock_loop,
        ):
            # time_limit_minutes=0 → limit_seconds=0 → immediate completion
            metrics = await runner.run_scenario(scenario, config)

        assert isinstance(metrics, BenchmarkMetrics)
        assert metrics.elapsed_seconds >= 0
        assert mock_loop.start.await_count == 1
        assert mock_loop.stop.await_count == 1
        # Bridge send_command was called (at least for seed/status)
        assert bridge.send_command.await_count >= 1

    async def test_runner_scenario_preserved_bridge_after_run(self):
        """Original bridge.send_command is restored after run_scenario."""
        bridge = make_bridge()
        original_send = bridge.send_command

        runner = BenchmarkRunner(bridge=bridge)

        scenario = BenchmarkScenario(
            name="Test",
            description="test",
            success_criteria={},
            time_limit_minutes=0,
        )
        config = BenchmarkConfig(
            name="Test",
            mode=BenchmarkMode.RULE_ONLY,
            time_limit_minutes=0,
        )

        mock_loop = MagicMock()
        mock_loop.start = AsyncMock()
        mock_loop.stop = AsyncMock()

        with patch(
            "animetta.tools.minecraft.benchmark.runner.AutonomousLoop",
            return_value=mock_loop,
        ):
            await runner.run_scenario(scenario, config)

        # Original send_command should be restored
        assert bridge.send_command is original_send

    async def test_runner_scenario_predefined_mode_uses_library(self):
        """PREDEFINED mode copies predefined skills into run library."""
        bridge = make_bridge()
        skill_lib = make_skill_library()

        # Set up predefined skills
        predefined = [make_skill("skill_a"), make_skill("skill_b")]
        runner = BenchmarkRunner(bridge=bridge, skill_library=skill_lib)
        runner._predefined_skills = predefined

        scenario = BenchmarkScenario(
            name="Test",
            description="test",
            success_criteria={},
            time_limit_minutes=0,
        )
        config = BenchmarkConfig(
            name="Test",
            mode=BenchmarkMode.PREDEFINED,
            time_limit_minutes=0,
        )

        mock_loop = MagicMock()
        mock_loop.start = AsyncMock()
        mock_loop.stop = AsyncMock()

        with patch(
            "animetta.tools.minecraft.benchmark.runner.AutonomousLoop",
            return_value=mock_loop,
        ):
            metrics = await runner.run_scenario(scenario, config)

        assert isinstance(metrics, BenchmarkMetrics)

    async def test_runner_scenario_full_voyager_copies_library(self):
        """FULL_VOYAGER mode copies existing skills into run library."""
        bridge = make_bridge()
        skill_lib = make_skill_library()

        # Make skill library return some skills
        existing_skills = [make_skill("existing_1"), make_skill("existing_2")]
        skill_lib.get_all_skills = AsyncMock(return_value=existing_skills)

        runner = BenchmarkRunner(bridge=bridge, skill_library=skill_lib)

        scenario = BenchmarkScenario(
            name="Test",
            description="test",
            success_criteria={},
            time_limit_minutes=0,
        )
        config = BenchmarkConfig(
            name="Test",
            mode=BenchmarkMode.FULL_VOYAGER,
            time_limit_minutes=0,
        )

        mock_loop = MagicMock()
        mock_loop.start = AsyncMock()
        mock_loop.stop = AsyncMock()

        with patch(
            "animetta.tools.minecraft.benchmark.runner.AutonomousLoop",
            return_value=mock_loop,
        ):
            metrics = await runner.run_scenario(scenario, config)

        assert isinstance(metrics, BenchmarkMetrics)

    async def test_runner_scenario_with_world_seed(self):
        """Scenario run sets world seed when config.world_seed is provided."""
        bridge = make_bridge()
        runner = BenchmarkRunner(bridge=bridge)

        scenario = BenchmarkScenario(
            name="Test",
            description="test",
            success_criteria={},
            time_limit_minutes=0,
        )
        config = BenchmarkConfig(
            name="Test",
            mode=BenchmarkMode.RULE_ONLY,
            world_seed="42",
            time_limit_minutes=0,
        )

        mock_loop = MagicMock()
        mock_loop.start = AsyncMock()
        mock_loop.stop = AsyncMock()

        with patch(
            "animetta.tools.minecraft.benchmark.runner.AutonomousLoop",
            return_value=mock_loop,
        ):
            await runner.run_scenario(scenario, config)

        # Verify /seed command was sent
        seed_calls = [
            c for c in bridge.send_command.call_args_list
            if c.args and c.args[0] == "chat"
        ]
        assert len(seed_calls) >= 1
        assert "/seed 42" in seed_calls[0].args[1]["message"]


class TestBenchmarkRunnerReport:
    """Test BenchmarkRunner.generate_report."""

    def test_generate_report_basic(self):
        """generate_report produces a markdown string."""
        bridge = make_bridge()
        runner = BenchmarkRunner(bridge=bridge)

        results = {
            "Survival Challenge": {
                "Rule-Only": BenchmarkMetrics(
                    completed=True,
                    elapsed_seconds=120,
                    unique_items_collected=3,
                    distance_traveled=500,
                    deaths=0,
                    skills_created=1,
                    task_success_rate=0.8,
                    final_inventory={"iron_pickaxe": 1, "iron_sword": 1},
                ),
                "LLM-Only": BenchmarkMetrics(
                    completed=False,
                    elapsed_seconds=120,
                    task_success_rate=0.5,
                ),
            },
        }

        report = runner.generate_report(results)

        assert isinstance(report, str)
        assert "Benchmark Report" in report
        assert "Survival Challenge" in report
        assert "Rule-Only" in report
        assert "LLM-Only" in report
        assert "Key Findings" in report

    def test_generate_report_single_result(self):
        """generate_report handles a single result entry."""
        bridge = make_bridge()
        runner = BenchmarkRunner(bridge=bridge)

        results = {
            "Solo Scenario": {
                "Only Config": BenchmarkMetrics(
                    completed=True,
                    elapsed_seconds=60,
                    task_success_rate=1.0,
                    unique_items_collected=2,
                    distance_traveled=100,
                    deaths=0,
                    skills_created=0,
                    final_inventory={"sword": 1},
                ),
            },
        }

        report = runner.generate_report(results)
        assert isinstance(report, str)
        assert "Benchmark Report" in report
        assert "Solo Scenario" in report

    def test_generate_report_best_config(self):
        """generate_report identifies the best configuration per scenario."""
        bridge = make_bridge()
        runner = BenchmarkRunner(bridge=bridge)

        results = {
            "Test Scenario": {
                "Good": BenchmarkMetrics(
                    completed=True,
                    task_success_rate=0.9,
                    unique_items_collected=10,
                ),
                "Bad": BenchmarkMetrics(
                    completed=False,
                    task_success_rate=0.1,
                    unique_items_collected=1,
                ),
            },
        }

        report = runner.generate_report(results)
        assert "Good" in report
        # Best config should be mentioned
        assert "Best configuration" in report or "completed" in report


class TestBenchmarkRunnerFullBenchmark:
    """Test BenchmarkRunner.run_full_benchmark."""

    async def test_run_full_benchmark_with_custom_scenarios(self):
        """run_full_benchmark iterates scenarios × configs."""
        bridge = make_bridge()
        skill_lib = make_skill_library()
        runner = BenchmarkRunner(bridge=bridge, skill_library=skill_lib)

        # Use a single minimal scenario + single config for speed
        scenario = BenchmarkScenario(
            name="Quick Test",
            description="minimal",
            success_criteria={},
            time_limit_minutes=0,
        )
        config = BenchmarkConfig(
            name="Rule-Only",
            mode=BenchmarkMode.RULE_ONLY,
            time_limit_minutes=0,
        )

        mock_loop = MagicMock()
        mock_loop.start = AsyncMock()
        mock_loop.stop = AsyncMock()

        with patch(
            "animetta.tools.minecraft.benchmark.runner.AutonomousLoop",
            return_value=mock_loop,
        ):
            results = await runner.run_full_benchmark(
                scenarios=[scenario],
                configs=[config],
            )

        assert "Quick Test" in results
        assert "Rule-Only" in results["Quick Test"]
        assert isinstance(results["Quick Test"]["Rule-Only"], BenchmarkMetrics)

    async def test_run_full_benchmark_predefined_triggers_load(self):
        """run_full_benchmark loads predefined skills when PREDEFINED config present."""
        bridge = make_bridge()
        skill_lib = make_skill_library()
        runner = BenchmarkRunner(bridge=bridge, skill_library=skill_lib)

        scenario = BenchmarkScenario(
            name="Test",
            description="test",
            success_criteria={},
            time_limit_minutes=0,
        )
        config = BenchmarkConfig(
            name="Predefined",
            mode=BenchmarkMode.PREDEFINED,
            time_limit_minutes=0,
        )

        mock_loop = MagicMock()
        mock_loop.start = AsyncMock()
        mock_loop.stop = AsyncMock()

        with (
            patch(
                "animetta.tools.minecraft.benchmark.runner.AutonomousLoop",
                return_value=mock_loop,
            ),
            patch.object(
                runner, "load_predefined_skills", new_callable=AsyncMock
            ) as mock_load,
        ):
            await runner.run_full_benchmark(
                scenarios=[scenario],
                configs=[config],
            )

        # load_predefined_skills should be called once
        mock_load.assert_awaited_once()
