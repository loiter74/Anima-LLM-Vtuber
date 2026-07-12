"""Audited real-server Voyager E2E against the external capability runtime.

Reset authority uses server RCON only before ``measurement_started_at``. After
that boundary, all state changes must flow through survival-safe runtime actions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from animetta.tools.minecraft.core.bridge import MinecraftBridge
from animetta.tools.minecraft.core.config import MinecraftConfig
from animetta.tools.minecraft.skill.catalog import SkillLibrary
from animetta.tools.minecraft.voyager.adapter import MinecraftGameBotAdapter
from animetta.tools.minecraft.voyager.contracts import (
    VoyagerCheckpoint,
    VoyagerMode,
    VoyagerSessionContext,
)
from animetta.tools.minecraft.voyager.learning import LearningSession
from animetta.tools.minecraft.voyager.policy import VoyagerPolicy
from animetta.tools.minecraft.voyager.recovery import RecoveryCoordinator
from animetta.tools.minecraft.voyager.repository import InMemoryVoyagerRepository
from animetta.tools.minecraft.voyager.tech_graph import (
    FrontierScheduler,
    TechGraph,
    TechProgress,
    build_survival_tech_graph,
)

BOT_USERNAME = "VoyagerAudit"
EXTERNAL_RUNTIME = Path(r"C:\Users\30262\Project\voyager-mc-bot")
ARTIFACT_DIR = Path("data/voyager-e2e")
REAL_ACTION_TIMEOUT_SECONDS = 180.0
FIXTURE_BIOME = "minecraft:forest"
FIXTURE_REGION_ATTEMPTS = 8
FIXTURE_MAX_ATTEMPTS = 8
MIN_FIXTURE_SURFACE_Y = 60.0
MAX_FIXTURE_SURFACE_Y = 75.0
FORBIDDEN_ACTIONS = {
    "give",
    "teleport",
    "creative",
    "set_inventory",
    "set_block",
    "rcon",
    "reset_world",
}
FORBIDDEN_CODE = {
    "process",
    "require",
    "constructor",
    "prototype",
    "globalThis",
    "fetch",
    "WebSocket",
    "rcon",
    "give",
    "teleport",
    "creative",
}


class StrategyGenerator:
    STRATEGIES = {
        "wood_collection": "await collect('oak_log', 1);",
        "crafting_table": (
            "await collect('oak_log', 1); await craft('oak_planks', 1); "
            "await craft('crafting_table', 1);"
        ),
        "wooden_pickaxe": (
            "await collect('oak_log', 2); await craft('oak_planks', 2); "
            "await craft('stick', 1); await craft('wooden_pickaxe', 1); "
            "await craft('wooden_sword', 1);"
        ),
        "cobblestone": (
            "await collect('oak_log', 2); await craft('oak_planks', 2); "
            "await craft('stick', 1); await craft('wooden_pickaxe', 1); "
            "await craft('wooden_sword', 1); "
            "await mine_shaft(50, 1);"
        ),
        "stone_pickaxe": (
            "await craft('stick', 2); await craft('stone_pickaxe', 1);"
        ),
        "furnace": "await craft('furnace', 1);",
        "iron_ingot": (
            "await collect('oak_log', 3); await craft('oak_planks', 3); "
            "await craft('crafting_table', 1); await craft('stick', 1); "
            "await craft('wooden_pickaxe', 1); await craft('wooden_sword', 1); "
            "await mine_shaft(55, 11); "
            "await craft('stone_pickaxe', 1); await craft('furnace', 1); "
            "await collect('raw_iron', 1); "
            "await collect('coal', 1); "
            "await smelt('raw_iron', 'coal', 1);"
        ),
        "iron_pickaxe": (
            "await craft('stick', 2); await craft('iron_pickaxe', 1);"
        ),
    }

    async def generate(self, *, node, observation=None, **_: Any) -> str:
        inventory = getattr(observation, "inventory", {}) or {}
        if (
            node.id == "cobblestone"
            and inventory.get("wooden_pickaxe", 0) >= 1
            and inventory.get("wooden_sword", 0) >= 1
        ):
            return "await mine_shaft(50, 1);"
        if node.id == "iron_pickaxe":
            actions: list[str] = []
            missing_iron = max(0, 3 - inventory.get("iron_ingot", 0))
            if missing_iron:
                actions.append(f"await collect('raw_iron', {missing_iron});")
                actions.append("await collect('coal', 1);")
                actions.append(
                    f"await smelt('raw_iron', 'coal', {missing_iron});"
                )
            if inventory.get("stick", 0) < 2:
                actions.append("await craft('stick', 1);")
            actions.append("await craft('iron_pickaxe', 1);")
            return " ".join(actions)
        if node.id == "stone_pickaxe":
            actions: list[str] = []
            missing_cobblestone = max(0, 3 - inventory.get("cobblestone", 0))
            recovered_tools = False
            if missing_cobblestone:
                has_pickaxe = any(
                    inventory.get(name, 0) >= 1
                    for name in ("wooden_pickaxe", "stone_pickaxe", "iron_pickaxe")
                )
                if not has_pickaxe:
                    actions.extend(
                        [
                            "await collect('oak_log', 3);",
                            "await craft('oak_planks', 3);",
                            "await craft('crafting_table', 1);",
                            "await craft('stick', 1);",
                            "await craft('wooden_pickaxe', 1);",
                            "await craft('wooden_sword', 1);",
                        ]
                    )
                    recovered_tools = True
                actions.append(f"await mine_shaft(50, {missing_cobblestone});")
            if inventory.get("stick", 0) < 2 and not recovered_tools:
                actions.append("await craft('stick', 1);")
            actions.append("await craft('stone_pickaxe', 1);")
            return " ".join(actions)
        if node.id == "furnace":
            missing_cobblestone = max(0, 8 - inventory.get("cobblestone", 0))
            if missing_cobblestone:
                return (
                    f"await collect('cobblestone', {missing_cobblestone}); "
                    "await craft('furnace', 1);"
                )
        if node.id == "iron_ingot" and inventory.get("iron_ingot", 0) >= 1:
            actions: list[str] = []
            if inventory.get("raw_iron", 0) < 1:
                actions.append("await collect('raw_iron', 1);")
            elif inventory.get("coal", 0) < 1:
                actions.append("await collect('coal', 1);")
            else:
                actions.append("await collect('cobblestone', 1);")
            if inventory.get("coal", 0) < 1:
                actions.append("await collect('coal', 1);")
            actions.append("await smelt('raw_iron', 'coal', 1);")
            return " ".join(actions)
        if node.id == "iron_ingot" and inventory.get("stone_pickaxe", 0) >= 1:
            actions: list[str] = []
            needs_sword = not any(
                inventory.get(name, 0) >= 1
                for name in ("wooden_sword", "stone_sword", "iron_sword")
            )
            support_target = 6 if needs_sword else 4
            missing_support = max(0, support_target - inventory.get("cobblestone", 0))
            if missing_support:
                actions.append(f"await collect('cobblestone', {missing_support});")
            if needs_sword:
                if inventory.get("stick", 0) < 1:
                    actions.append("await craft('stick', 1);")
                actions.append("await craft('stone_sword', 1);")
            actions.extend(
                [
                    "await mine_shaft(55);",
                    "await collect('raw_iron', 1);",
                    "await collect('coal', 1);",
                    "await smelt('raw_iron', 'coal', 1);",
                ]
            )
            return " ".join(actions)
        if node.id in {"stone_pickaxe", "iron_pickaxe"} and inventory.get(
            "stick", 0
        ) >= 2:
            return f"await craft('{node.id}', 1);"
        return self.STRATEGIES[node.id]


class AuditBridge:
    def __init__(self, bridge: MinecraftBridge) -> None:
        self._bridge = bridge
        self.commands: list[dict[str, Any]] = []
        self.violations: list[str] = []

    @property
    def is_running(self) -> bool:
        return self._bridge.is_running

    async def send_command(
        self, action: str, params: dict[str, Any] | None = None, timeout: float = 60.0
    ) -> dict[str, Any]:
        payload = dict(params or {})
        self.commands.append({"action": action, "params": payload})
        if action in FORBIDDEN_ACTIONS:
            self.violations.append(f"forbidden action:{action}")
        if action == "eval_skill":
            code = str(payload.get("code", ""))
            for token in FORBIDDEN_CODE:
                if token in code:
                    self.violations.append(f"forbidden code:{token}")
        return await self._bridge.send_command(action, payload, timeout=timeout)


def rcon(command: str) -> str:
    result = subprocess.run(
        ["docker", "exec", "animetta-mc", "rcon-cli", command],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def parse_locate_coordinates(output: str) -> tuple[int, int]:
    match = re.search(r"\[(-?\d+),\s*-?\d+,\s*(-?\d+)\]", output)
    if match is None:
        raise ValueError(f"cannot parse locate output: {output}")
    return int(match.group(1)), int(match.group(2))


def fixture_search_origin(run_index: int) -> tuple[int, int]:
    if run_index < 1:
        raise ValueError("run_index must be positive")
    offset = run_index * 2048
    return 20000 + offset, 20000 - offset


def natural_ground_check_passed(output: str) -> bool:
    """Return whether the conditional RCON probe reached its success command."""
    normalized = output.casefold()
    return BOT_USERNAME.casefold() in normalized and "experience point" in normalized


def parse_entity_y(output: str) -> float:
    """Parse the Y coordinate from an RCON ``data get entity ... Pos`` result."""
    match = re.search(
        r"\[\s*-?\d+(?:\.\d+)?d?,\s*(-?\d+(?:\.\d+)?)d?,",
        output,
    )
    if match is None:
        raise ValueError(f"cannot parse entity position output: {output}")
    return float(match.group(1))


async def position_player_on_natural_ground(
    forest_x: int,
    forest_z: int,
    audit: list[dict[str, str]],
    *,
    max_attempts: int = FIXTURE_MAX_ATTEMPTS,
) -> None:
    """Choose a fresh natural-grass landing before the measurement boundary."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")

    probe = (
        f"execute at {BOT_USERNAME} "
        "if block ~ ~-1 ~ minecraft:grass_block "
        f"run experience query {BOT_USERNAME} points"
    )
    position_query = f"data get entity {BOT_USERNAME} Pos"
    for attempt in range(max_attempts):
        radius = 16 + attempt * 8
        spread = f"spreadplayers {forest_x} {forest_z} 2 {radius} false {BOT_USERNAME}"
        outputs: dict[str, str] = {}
        for command in (spread, probe, position_query):
            output = await asyncio.to_thread(rcon, command)
            audit.append({"command": command, "output": output})
            outputs[command] = output
        try:
            surface_y = parse_entity_y(outputs[position_query])
        except ValueError:
            surface_y = float("inf")
        if (
            natural_ground_check_passed(outputs[probe])
            and MIN_FIXTURE_SURFACE_Y <= surface_y <= MAX_FIXTURE_SURFACE_Y
        ):
            return
        await asyncio.sleep(1)

    raise RuntimeError(
        f"could not place {BOT_USERNAME} on natural grass after {max_attempts} attempts"
    )


async def reset_player_before_measurement() -> list[dict[str, str]]:
    before_respawn = [
        f"gamemode survival {BOT_USERNAME}",
        f"clear {BOT_USERNAME}",
        f"kill {BOT_USERNAME}",
    ]
    audit = []
    for command in before_respawn:
        output = await asyncio.to_thread(rcon, command)
        audit.append({"command": command, "output": output})
    await asyncio.sleep(3)

    progression_runs = len(list(ARTIFACT_DIR.glob("*-progression.json")))
    positioned = False
    for region_attempt in range(FIXTURE_REGION_ATTEMPTS):
        region_index = progression_runs * FIXTURE_REGION_ATTEMPTS + region_attempt + 1
        search_x, search_z = fixture_search_origin(region_index)
        locate_command = (
            f"execute positioned {search_x} 100 {search_z} "
            f"run locate biome {FIXTURE_BIOME}"
        )
        locate_output = await asyncio.to_thread(rcon, locate_command)
        audit.append({"command": locate_command, "output": locate_output})
        forest_x, forest_z = parse_locate_coordinates(locate_output)
        try:
            await position_player_on_natural_ground(forest_x, forest_z, audit)
        except RuntimeError:
            continue
        positioned = True
        break
    if not positioned:
        raise RuntimeError(
            f"could not locate a bounded lowland {FIXTURE_BIOME} fixture "
            f"across {FIXTURE_REGION_ATTEMPTS} regions"
        )
    after_respawn = [
        f"effect clear {BOT_USERNAME}",
        f"experience set {BOT_USERNAME} 0 points",
        f"execute at {BOT_USERNAME} run kill @e[type=item,distance=..16]",
        "time set day",
        "weather clear",
        f"execute at {BOT_USERNAME} run kill @e[type=minecraft:skeleton,distance=..64]",
        f"execute at {BOT_USERNAME} run kill @e[type=minecraft:zombie,distance=..64]",
        f"execute at {BOT_USERNAME} run kill @e[type=minecraft:creeper,distance=..64]",
    ]
    for command in after_respawn:
        output = await asyncio.to_thread(rcon, command)
        audit.append({"command": command, "output": output})
    await asyncio.sleep(3)
    return audit


def build_config() -> MinecraftConfig:
    return MinecraftConfig.model_validate(
        {
            "enabled": True,
            "bot": {
                "host": "localhost",
                "port": 25565,
                "username": BOT_USERNAME,
                "version": "1.21",
            },
            "runtime": {
                "runtime_path": str(EXTERNAL_RUNTIME),
                "entrypoint": "src/index.js",
            },
        }
    )


def policy_for(manifest) -> VoyagerPolicy:
    return VoyagerPolicy(
        supported_protocol="1.0",
        allowed_capabilities={capability.name for capability in manifest.capabilities},
    )


def technology_node_completed(
    outcome: Any,
    expected_node: str,
    unlocked_nodes: set[str] | frozenset[str],
) -> bool:
    """Judge technology completion independently from candidate/trusted skill state."""

    return (
        outcome.status in {"candidate", "trusted"}
        and outcome.node_id == expected_node
        and expected_node in unlocked_nodes
    )


async def negative_runtime_audit(
    bridge: MinecraftBridge,
    runtime: MinecraftGameBotAdapter,
) -> dict[str, Any]:
    before = await runtime.observe("negative-before")
    attempts = []
    forbidden_code = [
        "process.exit(0)",
        "require('fs')",
        "({}).constructor.constructor('return process')()",
        "Object.getPrototypeOf({})",
        "await fetch('https://example.com')",
        "await collect['con' + 'structor']('return pro' + 'cess')()",
    ]
    for index, code in enumerate(forbidden_code, 1):
        result = await bridge.send_command(
            "eval_skill",
            {
                "code": code,
                "allowed_capabilities": ["collect"],
                "session_id": "negative-session",
                "task_id": f"negative-code-{index}",
                "correlation_id": f"negative-code-{index}",
            },
            timeout=10.0,
        )
        attempts.append({"kind": "code", "source": code, "response": result})

    for capability in sorted(FORBIDDEN_ACTIONS):
        result = await bridge.send_command(
            "execute_action",
            {
                "capability": capability,
                "params": {},
                "session_id": "negative-session",
                "task_id": f"negative-action-{capability}",
                "correlation_id": f"negative-action-{capability}",
            },
            timeout=10.0,
        )
        attempts.append(
            {"kind": "capability", "capability": capability, "response": result}
        )

    chat = await bridge.send_command(
        "execute_action",
        {
            "capability": "chat",
            "params": {"message": f"/give {BOT_USERNAME} diamond 64"},
            "session_id": "negative-session",
            "task_id": "negative-chat",
            "correlation_id": "negative-chat",
        },
        timeout=10.0,
    )
    attempts.append({"kind": "admin_chat", "response": chat})
    after = await runtime.observe("negative-after")
    if after.inventory != before.inventory:
        raise AssertionError(
            f"negative runtime audit changed inventory: {before.inventory} -> {after.inventory}"
        )
    return {
        "attempts": attempts,
        "inventory_before": before.inventory,
        "inventory_after": after.inventory,
    }


async def single_action_audit(runtime: MinecraftGameBotAdapter) -> dict[str, Any]:
    before = await runtime.observe("single-action-before")
    execution = await runtime.eval_skill(
        "await collect('oak_log', 1);",
        allowed_capabilities=["collect"],
        session_id="single-action-session",
        task_id="single-action-wood",
        correlation_id="single-action-wood",
        timeout=60.0,
    )
    after = await runtime.observe("single-action-after")
    return {
        "before": before.model_dump(mode="json"),
        "execution": execution.model_dump(mode="json"),
        "after": after.model_dump(mode="json"),
    }


async def run_progression(
    runtime: MinecraftGameBotAdapter,
    manifest,
) -> tuple[dict[str, Any], InMemoryVoyagerRepository, str, TechProgress]:
    node_ids = [
        "wood_collection",
        "crafting_table",
        "wooden_pickaxe",
        "cobblestone",
        "stone_pickaxe",
        "furnace",
        "iron_ingot",
        "iron_pickaxe",
    ]
    full_graph = build_survival_tech_graph()
    graph = TechGraph([full_graph.get(node_id) for node_id in node_ids])
    repository = InMemoryVoyagerRepository()
    session_id = "real-e2e-learning"
    context = VoyagerSessionContext(
        session_id=session_id,
        mode=VoyagerMode.LEARN,
        runtime=runtime,
        manifest=manifest,
        authorized_capabilities=frozenset(
            capability.name for capability in manifest.capabilities
        ),
        repository=repository,
    )
    library = SkillLibrary()
    session = LearningSession(
        context=context,
        graph=graph,
        scheduler=FrontierScheduler(graph, failure_cooldown=1),
        policy=policy_for(manifest),
        library=library,
        code_generator=StrategyGenerator(),
        progress=TechProgress(),
        max_attempts=2,
        execution_timeout=REAL_ACTION_TIMEOUT_SECONDS,
        validate_candidates=False,
    )
    outcomes, completed = await advance_progression(session, node_ids)

    checkpoint = await repository.last_checkpoint(session_id)
    skills = await library.get_all_skills()
    return (
        {
            "completed": completed,
            "outcomes": outcomes,
            "unlocked": sorted(session.progress.unlocked_nodes),
            "unlock_records": {
                key: value.model_dump(mode="json")
                for key, value in session.progress.records.items()
            },
            "trusted_skills": [skill.id for skill in skills if skill.is_trusted],
            "checkpoint": checkpoint.model_dump(mode="json") if checkpoint else None,
        },
        repository,
        session_id,
        session.progress,
    )


async def advance_progression(
    session: Any,
    node_ids: list[str],
    *,
    max_cycles: int | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Advance every target node without imposing an order on parallel frontiers."""

    targets = set(node_ids)
    outcomes: list[dict[str, Any]] = []
    cycle_limit = max_cycles if max_cycles is not None else len(node_ids) * 3
    for _ in range(cycle_limit):
        if targets.issubset(session.progress.unlocked_nodes):
            return outcomes, True
        try:
            outcome = await session.run_once()
        except Exception as exc:
            outcomes.append(
                {
                    "status": "exception",
                    "node_id": "",
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
            return outcomes, False
        outcomes.append(outcome.model_dump(mode="json"))
        if outcome.status in {"candidate", "trusted"} and (
            outcome.node_id not in targets
            or outcome.node_id not in session.progress.unlocked_nodes
        ):
            return outcomes, False
    return outcomes, targets.issubset(session.progress.unlocked_nodes)


async def recovery_audit(
    bridge: MinecraftBridge,
    runtime: MinecraftGameBotAdapter,
    repository: InMemoryVoyagerRepository,
    session_id: str,
    progress: TechProgress,
) -> dict[str, Any]:
    before = await runtime.observe("recovery-before")
    position = before.position
    if position is None:
        raise AssertionError("recovery test requires a player position")
    interrupted = asyncio.create_task(
        runtime.execute_action(
            "goto",
            {"x": position.x + 128, "y": position.y, "z": position.z + 128},
            session_id=session_id,
            task_id="interrupted-goto",
            correlation_id="interrupted-goto",
            timeout=60.0,
        )
    )
    await asyncio.sleep(1)
    if bridge._process is None:
        raise AssertionError("Node process is unavailable for restart audit")
    bridge._process.kill()
    interrupted_error = ""
    try:
        await interrupted
    except Exception as exc:  # Expected transport loss.
        interrupted_error = f"{type(exc).__name__}:{exc}"

    await bridge.stop()
    if not await bridge.start():
        raise RuntimeError("failed to restart Node runtime")
    coordinator = RecoveryCoordinator(runtime=runtime, repository=repository)
    result = await coordinator.recover(
        session_id=session_id,
        interrupted_task_id="interrupted-goto",
        active_correlation_id="interrupted-goto",
        partial_receipts=[],
    )
    if "interrupted-goto" in progress.unlocked_nodes:
        raise AssertionError("interrupted task incorrectly unlocked technology")
    return {
        "interrupted_error": interrupted_error,
        "result": result.model_dump(mode="json"),
        "unlocked_after_restart": sorted(progress.unlocked_nodes),
    }


async def main(mode: str) -> None:
    bridge = MinecraftBridge(build_config(), autonomous=False)
    artifact: dict[str, Any] = {
        "mode": mode,
        "bot": BOT_USERNAME,
        "reset_authority": "docker rcon before measurement only",
    }
    try:
        if not await bridge.start():
            raise RuntimeError("failed to start external Node runtime")
        artifact["reset"] = await reset_player_before_measurement()
        artifact["measurement_started_at"] = datetime.now(UTC).isoformat()

        audited_bridge = AuditBridge(bridge)
        runtime = MinecraftGameBotAdapter(audited_bridge)
        manifest = await runtime.get_capabilities()
        baseline = await runtime.observe("baseline")
        if baseline.inventory:
            raise AssertionError(f"reset did not produce empty inventory: {baseline.inventory}")
        artifact["manifest"] = manifest.model_dump(mode="json")
        artifact["baseline"] = baseline.model_dump(mode="json")

        if mode in {"negative", "all"}:
            artifact["negative"] = await negative_runtime_audit(bridge, runtime)

        if mode == "action":
            artifact["action"] = await single_action_audit(runtime)

        if mode == "recovery":
            repository = InMemoryVoyagerRepository()
            session_id = "real-e2e-recovery"
            await repository.commit_checkpoint(
                VoyagerCheckpoint(
                    session_id=session_id,
                    task_id="baseline-checkpoint",
                    observation_hash=baseline.content_hash,
                    metadata={"inventory": dict(baseline.inventory)},
                )
            )
            artifact["recovery"] = await recovery_audit(
                bridge,
                runtime,
                repository,
                session_id,
                TechProgress(),
            )

        if mode in {"progression", "all"}:
            progression, repository, session_id, progress = await run_progression(
                runtime, manifest
            )
            artifact["progression"] = progression
            if not progression["completed"]:
                raise AssertionError(
                    f"progression stopped: {progression['outcomes'][-1]}"
                )
            if mode in {"recovery", "all"}:
                artifact["recovery"] = await recovery_audit(
                    bridge,
                    runtime,
                    repository,
                    session_id,
                    progress,
                )

        if audited_bridge.violations:
            raise AssertionError(f"positive audit violations: {audited_bridge.violations}")
        artifact["protocol_commands"] = audited_bridge.commands
        artifact["passed"] = True
    except Exception as exc:
        artifact["passed"] = False
        artifact["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        artifact["finished_at"] = datetime.now(UTC).isoformat()
        if "audited_bridge" in locals():
            artifact.setdefault("protocol_commands", audited_bridge.commands)
            artifact.setdefault("audit_violations", audited_bridge.violations)
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        output = ARTIFACT_DIR / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{mode}.json"
        output.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        await bridge.stop()
        print(output.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("smoke", "negative", "action", "progression", "recovery", "all"),
        default="smoke",
    )
    args = parser.parse_args()
    asyncio.run(main(args.mode))
