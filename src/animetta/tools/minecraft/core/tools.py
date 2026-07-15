"""
Minecraft gameplay tools for Anima LLM

Each tool maps to a Mineflayer bot action and is registered as a LangChain @tool.
The bridge (MinecraftBridge) manages the Node.js subprocess lifecycle.
"""

import asyncio  # noqa: F401  (patch anchor: tests/tools/minecraft/core/test_bridge.py)
import json
from typing import Any

from langchain_core.tools import tool
from loguru import logger

# Global bridge instance (initialized by init_bridge)
_bridge = None
_voyager_controller = None
_voyager_library = None
# Global state collector (set by MinecraftHandlers after start)
_state_collector = None


def init_bridge(config: dict | None = None):
    """Initialize the Minecraft bridge (called from load_tools_from_config)

    Args:
        config: Minecraft config dict from tools.yaml
    """
    global _bridge
    if _bridge is not None:
        return

    from . import bridge as bridge_module
    from .bridge import MinecraftBridge
    from .config import MinecraftConfig

    mc_config = MinecraftConfig(**(config or {}))

    if not mc_config.enabled:
        logger.info("[MinecraftTools] Minecraft gameplay is disabled in config")
        return

    # Try to get ServicePool for LLM-powered learning loop
    service_pool_ref = None
    try:
        from animetta.core.service_pool import ServicePool

        if ServicePool._ready:
            service_pool_ref = ServicePool
    except Exception:
        pass

    _bridge = MinecraftBridge(
        mc_config,
        autonomous=False,
        service_pool=service_pool_ref,
    )
    bridge_module._bridge = _bridge

    # Bridge is created but NOT started here.
    # Callers should await _bridge.start() explicitly.
    logger.info("[MinecraftTools] Bridge created (not started yet)")


async def cleanup_bridge():
    """Cleanup bridge resources (called from ToolManager.cleanup)"""
    global _bridge, _voyager_controller, _voyager_library
    if _voyager_controller is not None:
        await _voyager_controller.stop()
        _voyager_controller = None
    if _voyager_library is not None:
        await _voyager_library.close_db()
        _voyager_library = None
    if _bridge:
        await _bridge.stop()
        _bridge = None
        from . import bridge as bridge_module

        bridge_module._bridge = None
        logger.info("[MinecraftTools] Bridge cleaned up")


async def configure_voyager_controller(
    bridge: Any,
    *,
    llm_service: Any,
    library: Any = None,
    repository: Any = None,
):
    """Compose the sole Voyager controller around a running game-bot runtime."""
    global _voyager_controller, _voyager_library

    from animetta.tools.minecraft.skill.catalog import SkillLibrary
    from animetta.tools.minecraft.survival.runner import SurvivalIronRunner
    from animetta.tools.minecraft.voyager.adapter import MinecraftGameBotAdapter
    from animetta.tools.minecraft.voyager.contracts import VoyagerMode
    from animetta.tools.minecraft.voyager.controller import VoyagerController
    from animetta.tools.minecraft.voyager.learning import (
        FrontierLLMCodeGenerator,
        LearningSession,
    )
    from animetta.tools.minecraft.voyager.live import FallbackSession, LiveSession
    from animetta.tools.minecraft.voyager.policy import VoyagerPolicy
    from animetta.tools.minecraft.voyager.recovery import RecoveryCoordinator
    from animetta.tools.minecraft.voyager.repository import InMemoryVoyagerRepository
    from animetta.tools.minecraft.voyager.tech_graph import (
        FrontierScheduler,
        TechProgress,
        build_survival_tech_graph,
    )

    if _voyager_controller is not None:
        await _voyager_controller.stop()
    if _voyager_library is not None and _voyager_library is not library:
        await _voyager_library.close_db()

    runtime = MinecraftGameBotAdapter(bridge)
    skill_library = library or SkillLibrary(db_path="data/minecraft_skills.db")
    await skill_library.init_db()
    voyager_repository = repository or InMemoryVoyagerRepository()
    graph = build_survival_tech_graph()
    allowed_capabilities = {
        "observe",
        "status",
        "goto",
        "collect",
        "mine",
        "craft",
        "place",
        "smelt",
        "equip",
        "attack",
        "chat",
        "recipes",
        "mine_shaft",
    }
    policy = VoyagerPolicy(
        supported_protocol="1.0",
        allowed_capabilities=allowed_capabilities,
    )
    generator = FrontierLLMCodeGenerator(llm_service)

    async def run_fallback(goal: str, *, task_id: str) -> dict[str, Any]:
        del goal, task_id
        report = await SurvivalIronRunner(bridge, skill_library=skill_library).run()
        return report.summary()

    def fallback_factory(context):
        return FallbackSession(context=context, runner=run_fallback)

    def learning_factory(context):
        return LearningSession(
            context=context,
            graph=graph,
            scheduler=FrontierScheduler(graph),
            policy=policy,
            library=skill_library,
            code_generator=generator,
            progress=TechProgress(),
        )

    def live_factory(context):
        return LiveSession(
            context=context,
            library=skill_library,
            policy=policy,
            fallback=fallback_factory(context),
        )

    controller = VoyagerController(
        runtime=runtime,
        policy=policy,
        session_factories={
            VoyagerMode.LEARN: learning_factory,
            VoyagerMode.LIVE: live_factory,
            VoyagerMode.FALLBACK: fallback_factory,
        },
        repository=voyager_repository,
        recovery=RecoveryCoordinator(runtime=runtime, repository=voyager_repository),
    )
    _voyager_controller = controller
    _voyager_library = skill_library
    return controller


def get_minecraft_tools() -> list[Any]:
    """Get all minecraft tools for registration

    Returns:
        List of LangChain tool objects
    """
    return [
        mc_goto,
        mc_mine,
        mc_build,
        mc_attack,
        mc_chat,
        mc_status,
        mc_goal,
        mc_stop,
        mc_collect,
        mc_craft,
        mc_smelt,
        mc_recipes,
        mc_survival_iron,
        mc_voyager_learn,
        mc_voyager_live,
    ]


async def _send(action: str, params: dict | None = None, timeout: float = 60.0) -> str:
    """Send command via bridge and format result for LLM consumption"""
    global _bridge
    if _bridge is None or not _bridge.is_running:
        return (
            "Minecraft bot is not connected. "
            "Make sure the Minecraft server is running and 'minecraft.enabled' is set to true in tools.yaml."
        )

    # Notify state collector of action
    if _state_collector is not None:
        target = ""
        if params:
            if action == "mine_block":
                target = params.get("block_type", "")
            elif action == "goto":
                target = f"({params.get('x', 0)},{params.get('y', 0)},{params.get('z', 0)})"
            elif action == "craft_item":
                target = params.get("item_name", "")
            elif action == "chop_tree":
                target = params.get("tree_type", "tree")
        _state_collector.update_action(action, target)

    result = await _bridge.send_command(action, params, timeout=timeout)

    status = result.get("status", "error")
    payload = result.get("result", "No result returned")

    if status == "error":
        return f"Action failed: {payload}"

    # If result is a dict (like status response), format it nicely
    if isinstance(payload, dict):
        lines = []
        for key, value in payload.items():
            if isinstance(value, dict):
                lines.append(f"{key}: {value}")
            elif isinstance(value, list):
                lines.append(f"{key}: {', '.join(str(v) for v in value)}")
            else:
                lines.append(f"{key}: {value}")
        return "\n".join(lines)

    return str(payload)


@tool
async def mc_goto(x: int, y: int, z: int) -> str:
    """Move the Minecraft character to specific XYZ coordinates.
    Use this to explore, travel to a location, or approach a target.
    The bot will automatically find a path using A* pathfinding.

    Args:
        x: Target X coordinate
        y: Target Y coordinate (height)
        z: Target Z coordinate
    """
    return await _send("goto", {"x": x, "y": y, "z": z})


@tool
async def mc_mine(block_type: str, count: int = 1) -> str:
    """Mine blocks of a specific type in Minecraft.
    The bot finds the nearest matching block within 10 blocks and digs it.
    Use this to collect resources like wood, stone, ores, etc.

    Args:
        block_type: Type of block to mine (e.g. 'oak_log', 'stone', 'diamond_ore', 'coal_ore')
        count: Number of blocks to mine (default: 1, max: 64)
    """
    return await _send("mine", {"block_type": block_type, "count": min(count, 64)})


@tool
async def mc_build(block_type: str, x: int, y: int, z: int) -> str:
    """Place a block at specific coordinates in Minecraft.
    There must be a solid block below the target position.
    Use this to build structures, walls, floors, bridges, etc.

    Args:
        block_type: Type of block to place (e.g. 'dirt', 'stone', 'oak_planks', 'glass')
        x: X coordinate to place at
        y: Y coordinate to place at
        z: Z coordinate to place at
    """
    return await _send("place", {"block_type": block_type, "x": x, "y": y, "z": z})


@tool
async def mc_attack(target: str = "nearest_hostile") -> str:
    """Attack a nearby entity in Minecraft.
    Use this to fight monsters and defend yourself.

    Args:
        target: What to attack.
            'nearest_hostile' - attack the nearest hostile mob (creeper, zombie, skeleton, etc.)
            'nearest_player' - attack the nearest player
            '<entity_name>' - attack a specific entity by name (e.g. 'Zombie', 'Creeper')
    """
    return await _send("attack", {"target": target})


@tool
async def mc_chat(message: str) -> str:
    """Send a chat message in the Minecraft game chat.
    Use this to communicate with other players or announce actions.
    Messages are visible to all players on the server.

    Args:
        message: The chat message text to send
    """
    return await _send("chat", {"message": message})


@tool
async def mc_status() -> str:
    """Get the current status of the Minecraft character.
    Returns position, health, food level, dimension, weather, time of day,
    biome, inventory items, and nearby entities.
    Use this before other actions to assess the situation.
    """
    return await _send("status")


@tool
async def mc_goal(goal: str = "") -> str:
    """Set or clear an autonomous goal for the Minecraft character.
    When a goal is set, the bot will work towards it during idle moments
    (when no commands are being sent). This is useful for live streaming
    where the bot should keep doing something even without viewer input.
    Call with an empty string to clear the current goal.

    Args:
        goal: Description of what to do (e.g. 'Explore the cave', 'Collect wood',
              'Build a small house'). Empty string to clear the current goal.
    """
    return await _send("setgoal", {"goal": goal})


@tool
async def mc_stop() -> str:
    """Emergency stop - cancel all current actions, pathfinding, and combat.
    Use this if the bot is stuck, doing something wrong, or needs to reset.
    Also clears any autonomous goal.
    """
    return await _send("stop")


@tool
async def mc_collect(block_type: str, count: int = 1) -> str:
    """Collect blocks of a specific type and bring them to the bot's inventory.
    Unlike mc_mine which only digs, this will find, approach, mine, and pick up
    the blocks automatically. More reliable for collecting resources.

    Args:
        block_type: Type of block to collect (e.g. 'oak_log', 'stone', 'diamond_ore')
        count: Number of blocks to collect (default: 1)
    """
    return await _send("collect", {"block_type": block_type, "count": min(count, 64)})


@tool
async def mc_craft(recipe: str, count: int = 1) -> str:
    """Craft items in Minecraft. Requires sufficient materials in inventory.

    Args:
        recipe: Item name to craft (e.g. 'oak_planks', 'stick', 'stone_pickaxe', 'crafting_table')
        count: Number of items to craft (default: 1, max: 64)
    """
    return await _send("craft", {"recipe": recipe, "count": min(count, 64)})


@tool
async def mc_smelt(item: str, fuel: str, count: int = 1) -> str:
    """Smelt items in a furnace. Requires a furnace nearby and fuel in inventory.

    Args:
        item: Item to smelt (e.g. 'iron_ore', 'sand', 'raw_iron')
        fuel: Fuel to use (e.g. 'coal', 'oak_log', 'charcoal')
        count: Number of items to smelt (default: 1, max: 64)
    """
    return await _send("smelt", {"item": item, "fuel": fuel, "count": min(count, 64)})


@tool
async def mc_recipes(item: str) -> str:
    """Query crafting recipes for an item. Shows required materials.

    Args:
        item: Item name to query (e.g. 'stone_pickaxe', 'furnace', 'iron_ingot')
    """
    return await _send("recipes", {"item": item})


@tool
async def mc_survival_iron() -> str:
    """Run a deterministic survival path from empty inventory to stable iron equipment.

    Phases: wood -> crafting_table -> wooden_pickaxe -> cobblestone -> stone_kit ->
    fuel -> iron_ore -> smelt_iron -> iron_gear.

    Returns a structured report with phase progress, final inventory, and
    success/failure status for each phase. This tool uses a state machine,
    not LLM planning, so it is reliable and deterministic.
    """
    return await _send("survival_iron", {}, timeout=60.0)


@tool
async def mc_voyager_learn() -> str:
    """Switch the Minecraft bot to Voyager offline LEARNING mode.

    In learn mode the bot runs the full Voyager 4-component loop offline
    (automatic curriculum → iterative code generation → skill library →
    self-verification) to accumulate a library of verified, reusable skills.
    This is offline exploration — it does NOT generate code during live streaming.
    Use mc_voyager_live to switch to the reliable live mode after training.
    """
    global _bridge, _voyager_controller
    if _bridge is None or not _bridge.is_running:
        return (
            "Minecraft bot is not connected. "
            "Make sure the Minecraft server is running and 'minecraft.enabled' is set to true in tools.yaml."
        )

    if _voyager_controller is None:
        return "Voyager controller is not configured. Restart the Minecraft integration."
    status = await _voyager_controller.start_learning()
    return json.dumps(status.model_dump(mode="json"), ensure_ascii=False)


@tool
async def mc_voyager_live(goal: str = "") -> str:
    """Switch to Voyager LIVE mode — reuse verified skills only, no new code generation.

    In live mode the bot selects skills from the verified library (by precondition
    match + success rate) and re-executes them. This is the reliable streaming mode.
    If all skills fail or the bot gets stuck, it automatically falls back to the
    deterministic Survival Runner.

    Args:
        goal: Optional goal to pursue immediately (e.g. 'collect wood', 'smelt iron').
              If omitted, the bot just enters live standby.
    """
    global _bridge, _voyager_controller
    if _bridge is None or not _bridge.is_running:
        return (
            "Minecraft bot is not connected. "
            "Make sure the Minecraft server is running and 'minecraft.enabled' is set to true in tools.yaml."
        )

    if _voyager_controller is None:
        return "Voyager controller is not configured. Restart the Minecraft integration."
    status = await _voyager_controller.start_live()
    if not goal:
        return json.dumps(status.model_dump(mode="json"), ensure_ascii=False)

    result = await _voyager_controller.run_live_goal(goal)
    return json.dumps(result, ensure_ascii=False, default=str)
