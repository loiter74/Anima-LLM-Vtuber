"""
State Collector — Periodically collects bot state and pushes to HUD + Socket.IO

Runs as a background task alongside MinecraftBridge.
Collects: status (health/food/position), inventory, nearby entities.
Pushes: MC HUD commands + Socket.IO events for web dashboard.

Usage:
    collector = StateCollector(bridge, sio, interval=2.0)
    await collector.start()
    ...
    await collector.stop()
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

from animetta.orchestration.socket_events import EVENTS

from .hud_renderer import BotHudState, render_actionbar, render_chat_action, render_sidebar_update

if TYPE_CHECKING:
    from socketio import AsyncServer

    from .bridge import MinecraftBridge


class StateCollector:
    """Collects bot state periodically and pushes to HUD + Socket.IO."""

    def __init__(
        self,
        bridge: MinecraftBridge,
        sio: AsyncServer | None = None,
        interval: float = 2.0,
    ) -> None:
        self._bridge = bridge
        self._sio = sio
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._running = False

        # Last known state (for delta detection)
        self._last_action: str = ""
        self._last_action_target: str = ""
        self._last_held_item: str = ""

    async def start(self) -> None:
        """Start the collection loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"[StateCollector] Started (interval={self._interval}s)")

    async def stop(self) -> None:
        """Stop the collection loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[StateCollector] Stopped")

    def update_action(self, action: str, target: str = "", held_item: str = "") -> None:
        """Called by tools when bot starts a new action.

        This triggers immediate HUD update (not waiting for next poll).
        """
        self._last_action = action
        self._last_action_target = target
        if held_item:
            self._last_held_item = held_item

        # Fire-and-forget immediate update
        if self._running:
            asyncio.create_task(self._push_action_update(action, target))

    async def _push_action_update(self, action: str, target: str) -> None:
        """Push immediate actionbar + chat update for action change."""
        try:
            state = BotHudState(
                current_action=action,
                action_target=target,
                held_item=self._last_held_item,
            )

            # Actionbar via /title command
            cmd = render_actionbar(state)
            await self._bridge.send_command("chat", {"message": f"/{cmd}"})

            # Chat notification
            chat_cmd = render_chat_action(state)
            if chat_cmd:
                await self._bridge.send_command("chat", {"message": f"/{chat_cmd}"})

            # Socket.IO
            await self._emit_state({"action": action, "target": target})

        except Exception as e:
            logger.debug(f"[StateCollector] Action update failed: {e}")

    async def _loop(self) -> None:
        """Main collection loop."""
        while self._running:
            try:
                await self._collect_and_push()
            except Exception as e:
                logger.debug(f"[StateCollector] Cycle error: {e}")
            await asyncio.sleep(self._interval)

    async def _collect_and_push(self) -> None:
        """Collect bot state and push to HUD + Socket.IO."""
        # 1. Get status
        status_resp = await self._bridge.send_command("status", {})
        if not isinstance(status_resp, dict) or status_resp.get("status") != "success":
            return

        status = status_resp.get("result", {})

        # 2. Get inventory
        inv_resp = await self._bridge.send_command("inventory", {})
        inventory = []
        if isinstance(inv_resp, dict) and inv_resp.get("status") == "success":
            inventory = inv_resp.get("result", {}).get("items", [])

        # Determine held item (first non-empty item or "empty hand")
        held = "empty hand"
        if inventory:
            first = inventory[0]
            held = f"{first.get('name', '?')} x{first.get('count', 1)}"

        # 3. Build state
        pos = status.get("position", {})
        state = BotHudState(
            current_action=self._last_action or "idle",
            action_target=self._last_action_target,
            held_item=held,
            health=status.get("health", 20),
            food=status.get("food", 20),
            x=pos.get("x", 0),
            y=pos.get("y", 0),
            z=pos.get("z", 0),
            dimension=status.get("dimension", "overworld"),
            biome=status.get("biome", "unknown"),
            time_of_day=status.get("time", "day"),
            weather=status.get("weather", "clear"),
        )

        # 4. Push MC HUD
        await self._push_hud(state)

        # 5. Push Socket.IO
        await self._emit_state({
            "health": state.health,
            "food": state.food,
            "position": {"x": state.x, "y": state.y, "z": state.z},
            "dimension": state.dimension,
            "biome": state.biome,
            "time": state.time_of_day,
            "weather": state.weather,
            "action": state.current_action,
            "action_target": state.action_target,
            "held_item": state.held_item,
            "inventory": inventory,
        })

    async def _push_hud(self, state: BotHudState) -> None:
        """Send HUD commands to MC server via bot.chat() (commands start with /)."""
        try:
            # Actionbar
            actionbar_cmd = render_actionbar(state)
            await self._bridge.send_command("chat", {"message": f"/{actionbar_cmd}"})

            # Sidebar
            for cmd in render_sidebar_update(state):
                await self._bridge.send_command("chat", {"message": f"/{cmd}"})

        except Exception as e:
            logger.debug(f"[StateCollector] HUD push failed: {e}")

    async def _emit_state(self, data: dict) -> None:
        """Emit bot state to Socket.IO for web dashboard."""
        if not self._sio:
            return
        try:
            await self._sio.emit(EVENTS["minecraft"]["bot_state"]["name"], data)
        except Exception as e:
            logger.debug(f"[StateCollector] Socket.IO emit failed: {e}")
