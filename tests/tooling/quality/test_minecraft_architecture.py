from __future__ import annotations

import subprocess
import sys
from pathlib import Path, PurePosixPath

from tooling.quality.minecraft_architecture import audit_repository, audit_source


def _codes(path: str, source: str) -> set[str]:
    return {violation.code for violation in audit_source(PurePosixPath(path), source)}


def test_audit_reports_direct_gameplay_calls_outside_executor_boundary() -> None:
    codes = _codes(
        "src/animetta/tools/minecraft/skill/executor.py",
        'async def run(bridge):\n    await bridge.send_command("mine", {})\n',
    )

    assert "DIRECT_GAMEPLAY_CALL" in codes


def test_audit_allows_runtime_adapter_and_command_executor_calls() -> None:
    source = 'async def run(runtime):\n    await runtime.execute_action("mine", {})\n'

    assert not _codes(
        "src/animetta/tools/minecraft/voyager/command_executor.py",
        source,
    )
    assert not _codes(
        "src/animetta/tools/minecraft/core/adapter.py",
        'async def run(bridge):\n    await bridge.send_command("gamebot_v2_execute", {})\n',
    )


def test_audit_reports_strategy_background_tasks_and_runtime_calls() -> None:
    codes = _codes(
        "src/animetta/tools/minecraft/voyager/strategies/live.py",
        """
import asyncio

async def run(runtime):
    asyncio.create_task(work())
    await runtime.execute_action("mine", {})
""",
    )

    assert {"STRATEGY_BACKGROUND_TASK", "DIRECT_GAMEPLAY_CALL"}.issubset(codes)


def test_audit_reports_legacy_execution_and_configuration_surfaces() -> None:
    execution_codes = _codes(
        "src/animetta/tools/minecraft/voyager/learning.py",
        """
async def run(runtime, skill):
    code = skill.body.get("code")
    await runtime.eval_skill(code)
    await bridge.send_command("eval_code", {"code": code})
""",
    )
    config_codes = _codes(
        "src/animetta/tools/minecraft/core/config.py",
        """
class MinecraftConfig:
    mode: str = "fallback"
    autonomous: bool = False
""",
    )

    assert {
        "PRODUCTION_EVAL_SKILL",
        "LEGACY_CODE_BODY",
        "DIRECT_GAMEPLAY_CALL",
    }.issubset(execution_codes)
    assert {"LEGACY_MODE_CONFIG", "LEGACY_AUTONOMOUS_CONFIG"}.issubset(config_codes)


def test_audit_reports_removed_public_tools_and_duplicate_graph_owner() -> None:
    tool_codes = _codes(
        "src/animetta/tools/minecraft/core/tools.py",
        """
@tool
async def mc_goto():
    return None

@tool
async def mc_connection():
    return None
""",
    )
    graph_codes = _codes(
        "src/animetta/tools/minecraft/voyager/tech_graph.py",
        "class TechGraph:\n    pass\n",
    )

    assert "OLD_PUBLIC_TOOL" in tool_codes
    assert "DUPLICATE_TECH_GRAPH_OWNER" in graph_codes


def test_audit_requires_exact_public_tool_surface() -> None:
    incomplete_codes = _codes(
        "src/animetta/tools/minecraft/core/tools.py",
        """
@tool
async def mc_connection():
    return None
""",
    )
    exact_codes = _codes(
        "src/animetta/tools/minecraft/core/tools.py",
        """
@tool(args_schema=ConnectionSchema)
async def mc_connection():
    return None

@tool(args_schema=OperateSchema)
async def mc_operate_bot():
    return None
""",
    )

    assert "PUBLIC_TOOL_SURFACE_MISMATCH" in incomplete_codes
    assert "PUBLIC_TOOL_SURFACE_MISMATCH" not in exact_codes


def test_audit_reports_domain_imports_of_control_plane_implementations() -> None:
    codes = _codes(
        "src/animetta/tools/minecraft/discovery/projector.py",
        """
from animetta.tools.minecraft.core.adapter import GameBotV2RuntimeAdapter
from animetta.tools.minecraft.voyager.gateway import VoyagerGateway
""",
    )

    assert "DOMAIN_CONTROL_PLANE_IMPORT" in codes


def test_audit_reports_duplicate_gameplay_scheduler_and_executor() -> None:
    codes = _codes(
        "src/animetta/tools/minecraft/mission/coordinator.py",
        """
class VoyagerCommandScheduler:
    pass

class CommandExecutor:
    pass
""",
    )

    assert "DUPLICATE_GAMEPLAY_SCHEDULER" in codes
    assert "DUPLICATE_COMMAND_EXECUTOR" in codes


def test_audit_reports_mission_and_discovery_runtime_calls() -> None:
    mission_codes = _codes(
        "src/animetta/tools/minecraft/mission/coordinator.py",
        'async def advance(runtime):\n    await runtime.execute_action("collect", {})\n',
    )
    discovery_codes = _codes(
        "src/animetta/tools/minecraft/discovery/projector.py",
        'async def project(bridge):\n    await bridge.send_command("observe", {})\n',
    )

    assert "DIRECT_GAMEPLAY_CALL" in mission_codes
    assert "DIRECT_GAMEPLAY_CALL" in discovery_codes


def test_repository_audit_rejects_sibling_runtime_paths(tmp_path: Path) -> None:
    target = tmp_path / "scripts" / "minecraft_probe.py"
    target.parent.mkdir(parents=True)
    target.write_text('runtime_path = "../voyager-mc-bot"\n', encoding="utf-8")

    violations = audit_repository(tmp_path)

    assert {item.code for item in violations} == {"ANIMA_MC_RUNTIME_COUPLING"}


def test_report_cli_runs_from_the_repository_root() -> None:
    root = Path(__file__).resolve().parents[3]

    completed = subprocess.run(
        [sys.executable, "scripts/check_minecraft_architecture.py", "--report"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("Minecraft architecture audit:")
