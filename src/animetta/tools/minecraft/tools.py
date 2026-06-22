"""
Minecraft gameplay tools for Anima LLM

Each tool maps to a Mineflayer bot action and is registered as a LangChain @tool.
The bridge (MinecraftBridge) manages the Node.js subprocess lifecycle.
"""

from typing import Any

from langchain_core.tools import tool
from loguru import logger

# Global bridge instance (initialized by init_bridge)
_bridge = None


def init_bridge(config: dict | None = None):
    """Initialize the Minecraft bridge (called from load_tools_from_config)

    Args:
        config: Minecraft config dict from tools.yaml
    """
    global _bridge
    if _bridge is not None:
        return

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
        autonomous=mc_config.autonomous,
        service_pool=service_pool_ref,
    )

    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            asyncio.ensure_future(_bridge.start())
        else:
            loop.run_until_complete(_bridge.start())
    except RuntimeError:
        # No running event loop -- use asyncio.run() which handles loop lifecycle
        asyncio.run(_bridge.start())

    logger.info("[MinecraftTools] Bridge initialized and bot connecting...")


async def cleanup_bridge():
    """Cleanup bridge resources (called from ToolManager.cleanup)"""
    global _bridge
    if _bridge:
        await _bridge.stop()
        _bridge = None
        logger.info("[MinecraftTools] Bridge cleaned up")


def get_minecraft_tools() -> list[Any]:
    """Get all minecraft tools for registration

    Returns:
        List of LangChain tool objects
    """
    return [mc_goto, mc_mine, mc_build, mc_attack, mc_chat, mc_status, mc_goal, mc_stop, mc_collect, mc_craft, mc_smelt, mc_recipes, mc_survival_iron]


# Import asyncio for bridge initialization
import asyncio


async def _send(action: str, params: dict | None = None, timeout: float = 60.0) -> str:
    """Send command via bridge and format result for LLM consumption"""
    global _bridge
    if _bridge is None or not _bridge.is_running:
        return (
            "Minecraft bot is not connected. "
            "Make sure the Minecraft server is running and 'minecraft.enabled' is set to true in tools.yaml."
        )

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
    global _bridge
    if _bridge is None or not _bridge.is_running:
        return (
            "Minecraft bot is not connected. "
            "Make sure the Minecraft server is running and 'minecraft.enabled' is set to true in tools.yaml."
        )

    from .survival_benchmark import summarize_run
    from .survival_runner import SurvivalIronRunner

    runner = SurvivalIronRunner(_bridge)
    report = await runner.run()

    summary = summarize_run(report)

    # Format for LLM consumption
    lines = [
        f"Survival Iron Run: {'COMPLETED' if report.completed else 'INCOMPLETE'}",
        f"Duration: {report.elapsed_seconds:.0f}s | Deaths: {report.deaths}",
        "",
        "Phase Progress:",
    ]
    for pr in report.phase_results:
        status = "PASS" if pr.success else "FAIL"
        fail = f" ({pr.failure_category.value}: {pr.failure_message})" if pr.failure_category else ""
        lines.append(f"  [{status}] {pr.phase.value} -- {pr.actions_succeeded}/{pr.actions_attempted} actions{fail}")

    lines.append("")
    lines.append("Final Inventory:")
    for item, count in sorted(report.final_inventory.items()):
        lines.append(f"  {item}: {count}")

    gear = summary.get("iron_gear_achieved", {})
    lines.append("")
    lines.append("Iron Gear:")
    for item, achieved in gear.items():
        mark = "YES" if achieved else "NO"
        lines.append(f"  {item}: {mark}")

    return "\n".join(lines)
