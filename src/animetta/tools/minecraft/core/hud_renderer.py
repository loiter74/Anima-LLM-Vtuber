"""
HUD Renderer — Generates Minecraft commands for in-game status display

Outputs three types of HUD elements:
- actionbar: Current action + held item (bottom of screen)
- sidebar: Vital stats, position, entity count (right side)
- chat: AI reasoning chain with color-coded formatting (chat log)

All methods return raw MC command strings to be executed via RCON or bot.chat().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BotHudState:
    """Snapshot of bot state for HUD rendering."""

    # Action
    current_action: str = "idle"
    action_target: str = ""
    held_item: str = "empty hand"

    # Vitals
    health: float = 20.0
    food: float = 20.0
    xp_level: int = 0

    # Position
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    dimension: str = "overworld"
    biome: str = "unknown"

    # Environment
    time_of_day: str = "day"
    weather: str = "clear"
    nearby_hostiles: int = 0
    nearby_passives: int = 0

    # AI reasoning
    reasoning: str = ""
    current_goal: str = ""

    @classmethod
    def from_world_state(cls, ws: Any) -> BotHudState:
        """Build from WorldState dataclass."""
        hostile = sum(1 for e in ws.entities if e.is_threat)
        passive = sum(1 for e in ws.entities if not e.is_threat)
        return cls(
            health=ws.health,
            food=ws.food,
            x=ws.x,
            y=ws.y,
            z=ws.z,
            dimension=ws.dimension,
            biome=ws.biome,
            time_of_day=ws.time,
            weather=ws.weather,
            nearby_hostiles=hostile,
            nearby_passives=passive,
            current_goal=ws.current_goal or "",
        )


def _bar(current: float, maximum: float, length: int = 10, filled: str = "▮", empty: str = "▯") -> str:
    """Render a text progress bar."""
    ratio = max(0.0, min(1.0, current / maximum))
    filled_count = round(ratio * length)
    return filled * filled_count + empty * (length - filled_count)


def _color_for_health(hp: float) -> str:
    """Return MC color name for health level."""
    if hp >= 16:
        return "green"
    if hp >= 10:
        return "yellow"
    return "red"


def _color_for_food(food: float) -> str:
    """Return MC color name for food level."""
    if food >= 16:
        return "green"
    if food >= 8:
        return "yellow"
    return "red"


# ── Actionbar (single line, bottom of screen) ──────────────────────


def render_actionbar(state: BotHudState) -> str:
    """Generate /title actionbar command.

    Shows: action + held item, e.g. "⛏ Mining iron_ore | 🗡 Iron Sword"
    """
    action_icons = {
        "idle": "⏸",
        "mine_block": "⛏",
        "chop_tree": "🪓",
        "craft_item": "🔨",
        "smelt_item": "🔥",
        "goto": "🚶",
        "place_block": "🧱",
        "attack": "⚔",
        "eat": "🍖",
        "pickup_item": "📥",
    }
    icon = action_icons.get(state.current_action, "🤖")
    action_text = f"{icon} {state.current_action}"
    if state.action_target:
        action_text += f" {state.action_target}"

    held = state.held_item
    display = f"{action_text}  │  🖐 {held}"

    # JSON text component with color
    payload = f'{{"text":"{display}","color":"aqua","bold":false}}'
    return f"title @a actionbar {payload}"


# ── Sidebar (right side list, max 15 lines) ────────────────────────


def render_sidebar_setup(state: BotHudState) -> list[str]:
    """Generate scoreboard setup commands (call once on init).

    Creates objectives and sets display.
    """
    cmds = [
        # Create objectives (ignore errors if already exist)
        "scoreboard objectives add hud_health health",
        "scoreboard objectives add hud_food food",
        "scoreboard objectives add hud_x dummy",
        "scoreboard objectives add hud_y dummy",
        "scoreboard objectives add hud_z dummy",
        "scoreboard objectives add hud_hostiles dummy",
        "scoreboard objectives add hud_passives dummy",
        # Title (sidebar header)
        'scoreboard objectives modify hud_health displayname {"text":"❤ Health","color":"red"}',
        'scoreboard objectives modify hud_food displayname {"text":"🍖 Food","color":"gold"}',
        'scoreboard objectives modify hud_x displayname {"text":"📍 X","color":"aqua"}',
        'scoreboard objectives modify hud_y displayname {"text":"📍 Y","color":"aqua"}',
        'scoreboard objectives modify hud_z displayname {"text":"📍 Z","color":"aqua"}',
        'scoreboard objectives modify hud_hostiles displayname {"text":"⚔ Hostiles","color":"red"}',
        'scoreboard objectives modify hud_passives displayname {"text":"🐄 Passives","color":"green"}',
    ]
    return cmds


def render_sidebar_update(state: BotHudState) -> list[str]:
    """Generate scoreboard update commands for sidebar.

    Shows: Health, Food, Position, Hostiles, Passives, Goal.
    Uses a single dummy objective 'hud_sidebar' with formatted lines.
    """
    bot = "AnimettaBot"

    hp_color = _color_for_health(state.health)
    food_color = _color_for_food(state.food)

    # Build sidebar using a single dummy objective with line ordering
    lines = [
        (15, f'{{"text":"━━━ Bot HUD ━━━","color":"gold","bold":true}}'),
        (14, f'{{"text":"❤ {state.health:.0f}/20 { _bar(state.health, 20)}","color":"{hp_color}"}}'),
        (13, f'{{"text":"🍖 {state.food:.0f}/20 { _bar(state.food, 20)}","color":"{food_color}"}}'),
        (12, f'{{"text":"📍 {state.x:.0f} {state.y:.0f} {state.z:.0f}","color":"aqua"}}'),
        (11, f'{{"text":"🌍 {state.dimension}","color":"white"}}'),
        (10, f'{{"text":"🌿 {state.biome}","color":"green"}}'),
        (9, f'{{"text":"⏰ {state.time_of_day} | {state.weather}","color":"yellow"}}'),
        (8, f'{{"text":"━━━ Entities ━━━","color":"gold","bold":true}}'),
        (7, f'{{"text":"⚔ Hostiles: {state.nearby_hostiles}","color":"red"}}'),
        (6, f'{{"text":"🐄 Passives: {state.nearby_passives}","color":"green"}}'),
    ]

    if state.current_goal:
        lines.append(
            (5, f'{{"text":"━━━ Goal ━━━","color":"gold","bold":true}}')
        )
        lines.append(
            (4, f'{{"text":"🎯 {state.current_goal[:30]}","color":"light_purple"}}')
        )

    cmds = [
        # Create/reset the sidebar objective
        "scoreboard objectives add hud_sidebar dummy",
        "scoreboard objectives setdisplay sidebar hud_sidebar",
    ]

    # Use fake player names for line ordering (higher score = higher on sidebar)
    for score, text_json in lines:
        # Escape quotes for command
        cmds.append(
            f"scoreboard players set line_{score} hud_sidebar {score}"
        )

    # We use a workaround: set display name of the objective itself + use entity scores
    # Actually, for proper sidebar with custom text, we need /tellraw or a different approach.
    # MC sidebar only shows player names + scores. For rich text, use actionbar + chat.

    # Simplified: use basic scoreboard with numeric values
    cmds = [
        "scoreboard objectives remove hud_sidebar",
        "scoreboard objectives add hud_sidebar dummy",
        'scoreboard objectives modify hud_sidebar displayname {"text":"━━ Bot HUD ━━","color":"gold","bold":true}',
        "scoreboard objectives setdisplay sidebar hud_sidebar",
        f"scoreboard players set ❤_Health hud_sidebar {int(state.health)}",
        f"scoreboard players set 🍖_Food hud_sidebar {int(state.food)}",
        f"scoreboard players set 📍_X hud_sidebar {int(state.x)}",
        f"scoreboard players set 📍_Y hud_sidebar {int(state.y)}",
        f"scoreboard players set 📍_Z hud_sidebar {int(state.z)}",
        f"scoreboard players set ⚔_Hostiles hud_sidebar {state.nearby_hostiles}",
        f"scoreboard players set 🐄_Passives hud_sidebar {state.nearby_passives}",
    ]

    if state.current_goal:
        # Truncate goal to fit scoreboard line
        goal_len = min(len(state.current_goal), 16)
        cmds.append(
            f"scoreboard players set 🎯_Goal hud_sidebar 0"
        )

    return cmds


# ── Chat (AI reasoning, color-coded) ───────────────────────────────


def render_chat_reasoning(state: BotHudState) -> str | None:
    """Generate /tellraw command for AI reasoning display.

    Returns None if no reasoning to display.
    """
    if not state.reasoning:
        return None

    # Truncate long reasoning
    text = state.reasoning[:100]
    if len(state.reasoning) > 100:
        text += "..."

    payload = (
        f'{{"text":"","extra":['
        f'{{"text":"[AI] ","color":"light_purple","bold":true}},'
        f'{{"text":"{text}","color":"white"}}'
        f']}}'
    )
    return f"tellraw @a {payload}"


def render_chat_action(state: BotHudState) -> str | None:
    """Generate /tellraw for action change notification."""
    if state.current_action == "idle":
        return None

    action_icons = {
        "mine_block": "⛏",
        "chop_tree": "🪓",
        "craft_item": "🔨",
        "smelt_item": "🔥",
        "goto": "🚶",
        "place_block": "🧱",
        "attack": "⚔",
        "eat": "🍖",
    }
    icon = action_icons.get(state.current_action, "🤖")
    target = f" → {state.action_target}" if state.action_target else ""

    payload = (
        f'{{"text":"","extra":['
        f'{{"text":"{icon} ","color":"yellow"}},'
        f'{{"text":"{state.current_action}{target}","color":"gold"}}'
        f']}}'
    )
    return f"tellraw @a {payload}"


# ── Combined render ────────────────────────────────────────────────


def render_full_update(state: BotHudState) -> dict[str, list[str]]:
    """Generate all HUD commands for a full state update.

    Returns dict with keys: 'actionbar', 'sidebar', 'chat'.
    Each value is a list of MC commands.
    """
    result: dict[str, list[str]] = {
        "actionbar": [],
        "sidebar": [],
        "chat": [],
    }

    # Actionbar
    result["actionbar"].append(render_actionbar(state))

    # Sidebar
    result["sidebar"].extend(render_sidebar_update(state))

    # Chat (reasoning only when present)
    chat_msg = render_chat_reasoning(state)
    if chat_msg:
        result["chat"].append(chat_msg)

    return result
