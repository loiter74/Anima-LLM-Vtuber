"""
Minecraft Gameplay Integration

Provides:
- MinecraftBridge for managing Mineflayer bot subprocess lifecycle
- LangChain @tool decorators for LLM-driven gameplay
- Config models for Minecraft server and safety settings
- BenchmarkRunner for comparing Voyager configurations
- TechTree phase-based progression system
- SurvivalIronRunner for deterministic wood-to-iron-gear progression
"""

from .loop import AutonomousLoop
from .main import (
    BUILDING_CHALLENGE,
    LEARNING_CHALLENGE,
    SURVIVAL_CHALLENGE,
    TECH_TREE_UNLOCK,
    BenchmarkConfig,
    BenchmarkMetrics,
    BenchmarkMode,
    BenchmarkRunner,
    BenchmarkScenario,
)
from .bridge import MinecraftBridge, get_bridge
from .config import MinecraftBotConfig, MinecraftConfig, MinecraftSafetyConfig
from .predefined import get_predefined_skills
from .loop.rules_engine import RulesEngine
from .extractor import SkillExtractor
from .library import SkillStep
from .validator import SimulatedState, SkillValidator, ValidationResult
from .benchmark.main import compare_runs, render_markdown_report, summarize_run
from .inventory import (
    all_goals_satisfied,
    find_fuel_item,
    normalize_inventory,
    normalize_item_name,
    resolve_block_type,
)
from .models import (
    IRON_SURVIVAL_GOALS,
    FailureCategory,
    InventoryGoal,
    PhaseResult,
    RunReport,
    SurvivalPhase,
)
from .recovery import (
    check_safety,
    map_collect_failure,
    map_craft_failure,
    map_smelt_failure,
)
from .runner import SurvivalIronRunner
from .main import (
    DIAMOND_PHASE,
    IRON_PHASE,
    STONE_PHASE,
    WOOD_PHASE,
    TechTreeConfig,
    TechTreeMetrics,
    TechTreePhase,
    TechTreeReport,
    TechTreeRunner,
    create_default_tech_tree,
)
from .tools import cleanup_bridge, get_minecraft_tools, init_bridge
from .trace_recorder import ActionTrace, TaskTrace, TraceRecorder
from .world_state import WorldState

__all__ = [
    "MinecraftBridge",
    "get_bridge",
    "get_minecraft_tools",
    "init_bridge",
    "cleanup_bridge",
    "MinecraftConfig",
    "MinecraftBotConfig",
    "MinecraftSafetyConfig",
    "AutonomousLoop",
    "RulesEngine",
    "WorldState",
    "SkillStep",
    "get_predefined_skills",
    "ActionTrace",
    "TaskTrace",
    "TraceRecorder",
    "SkillExtractor",
    "ValidationResult",
    "SimulatedState",
    "SkillValidator",
    "BenchmarkConfig",
    "BenchmarkMetrics",
    "BenchmarkMode",
    "BenchmarkRunner",
    "BenchmarkScenario",
    "BUILDING_CHALLENGE",
    "LEARNING_CHALLENGE",
    "SURVIVAL_CHALLENGE",
    "TECH_TREE_UNLOCK",
    "TechTreePhase",
    "TechTreeConfig",
    "TechTreeMetrics",
    "TechTreeReport",
    "TechTreeRunner",
    "WOOD_PHASE",
    "STONE_PHASE",
    "IRON_PHASE",
    "DIAMOND_PHASE",
    "create_default_tech_tree",
    # Survival iron-run
    "SurvivalIronRunner",
    "SurvivalPhase",
    "PhaseResult",
    "RunReport",
    "FailureCategory",
    "InventoryGoal",
    "IRON_SURVIVAL_GOALS",
    "normalize_item_name",
    "normalize_inventory",
    "all_goals_satisfied",
    "find_fuel_item",
    "resolve_block_type",
    "check_safety",
    "map_collect_failure",
    "map_craft_failure",
    "map_smelt_failure",
    "summarize_run",
    "render_markdown_report",
    "compare_runs",
]
