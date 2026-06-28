"""
Minecraft bot control handlers.

Manages the MinecraftBridge lifecycle (start/stop) via Socket.IO events.
Follows the same pattern as BilibiliHandlers: frontend emits events,
backend starts/stops the service and reports status back.
"""

from typing import TYPE_CHECKING

from loguru import logger

from ...socket_events import EVENTS
from ....tools.minecraft.core.tools import init_bridge, cleanup_bridge
from ....tools.minecraft.core.bridge import get_bridge
from ....tools.minecraft.core.config import MinecraftConfig
from ....tools.minecraft.core.state_collector import StateCollector
from ....tools.minecraft.core import tools as mc_tools

if TYPE_CHECKING:
    from socketio import AsyncServer


class MinecraftHandlers:
    """Minecraft bot lifecycle handlers.

    Receives sio for emitting status events back to the frontend.
    Uses the global Minecraft bridge singleton (init_bridge / cleanup_bridge).
    """

    def __init__(self, sio: "AsyncServer"):
        self.sio = sio
        self._state_collector: StateCollector | None = None

    def _setup_viewer_callback(self, bridge) -> None:
        """Register callback to forward viewer join/leave events to frontend."""

        def on_viewer_event(event_type: str, username: str) -> None:
            import asyncio
            status = "joined" if event_type == "viewer_joined" else "left"
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self.sio.emit(
                        EVENTS["minecraft"]["viewer_status"]["name"],
                        {"status": status, "username": username},
                    )
                )
            except RuntimeError:
                logger.warning("[Minecraft] No event loop for viewer callback")

        bridge.set_viewer_callback(on_viewer_event)

    async def on_minecraft_start(self, sid: str, data: dict) -> None:
        """Handle frontend request to start the Minecraft bot.

        Spawns the Mineflayer subprocess and registers Minecraft tools.
        Emits minecraft.status on success or failure.
        """
        try:

            config = MinecraftConfig(enabled=True, autonomous=True)
            logger.info("[Minecraft] Frontend requested start")

            # Init bridge (creates the singleton if not exists) and start
            init_bridge(config.model_dump())

            bridge = get_bridge()
            if bridge is None:
                await self.sio.emit(
                    EVENTS["minecraft"]["status"]["name"],
                    {"connected": False, "error": "Bridge initialization failed"},
                    to=sid,
                )
                return

            # Register viewer callback before starting
            self._setup_viewer_callback(bridge)

            # Start the bot (init_bridge only creates, doesn't start)
            await bridge.start()
            logger.info("[Minecraft] Bot started successfully")

            # Start state collector for HUD + web dashboard
            self._state_collector = StateCollector(bridge, self.sio, interval=2.0)
            mc_tools._state_collector = self._state_collector
            await self._state_collector.start()

            await self.sio.emit(
                EVENTS["minecraft"]["status"]["name"],
                {"connected": True, "username": config.bot.username},
                to=sid,
            )

            # If viewer is configured, emit initial waiting status
            if config.viewer.username:
                await self.sio.emit(
                    EVENTS["minecraft"]["viewer_status"]["name"],
                    {"status": "waiting", "username": config.viewer.username},
                    to=sid,
                )

        except Exception as e:
            logger.error(f"[Minecraft] Failed to start: {e}")
            await self.sio.emit(
                EVENTS["minecraft"]["status"]["name"],
                {"connected": False, "error": str(e)},
                to=sid,
            )

    async def on_minecraft_stop(self, sid: str, data: dict) -> None:
        """Handle frontend request to stop the Minecraft bot.

        Terminates the Mineflayer subprocess and cleans up the bridge.
        """
        try:

            logger.info("[Minecraft] Frontend requested stop")

            # Stop state collector first
            if self._state_collector:
                await self._state_collector.stop()
                self._state_collector = None
                mc_tools._state_collector = None

            bridge = get_bridge()
            if bridge is not None:
                await bridge.stop()
            await cleanup_bridge()

            logger.info("[Minecraft] Bot stopped")
            await self.sio.emit(
                EVENTS["minecraft"]["status"]["name"],
                {"connected": False},
                to=sid,
            )
        except ImportError:
            logger.warning("[Minecraft] Minecraft tools not installed")
            await self.sio.emit(
                EVENTS["minecraft"]["status"]["name"],
                {"connected": False, "error": "Minecraft tools not installed"},
                to=sid,
            )
        except Exception as e:
            logger.error(f"[Minecraft] Failed to stop: {e}")
            await self.sio.emit(
                EVENTS["minecraft"]["status"]["name"],
                {"connected": False, "error": str(e)},
                to=sid,
            )

    async def on_minecraft_spectate(self, sid: str, data: dict) -> None:
        """Handle frontend request to manually re-spectate the viewer.

        Sends spectate command to the bot, which executes /gamemode + /spectate.
        """
        try:
            bridge = get_bridge()
            if bridge is None or not bridge.is_running:
                await self.sio.emit(
                    EVENTS["minecraft"]["viewer_status"]["name"],
                    {"status": "error", "error": "Bot not running"},
                    to=sid,
                )
                return

            username = data.get("username") if isinstance(data, dict) else None
            result = await bridge.spectate_viewer(username)
            logger.info(f"[Minecraft] Spectate result: {result}")

            if result.get("status") == "success":
                await self.sio.emit(
                    EVENTS["minecraft"]["viewer_status"]["name"],
                    {"status": "joined", "username": username or ""},
                    to=sid,
                )
            else:
                await self.sio.emit(
                    EVENTS["minecraft"]["viewer_status"]["name"],
                    {"status": "error", "error": str(result.get("result", "Unknown error"))},
                    to=sid,
                )

        except Exception as e:
            logger.error(f"[Minecraft] Spectate failed: {e}")
            await self.sio.emit(
                EVENTS["minecraft"]["viewer_status"]["name"],
                {"status": "error", "error": str(e)},
                to=sid,
            )

    async def on_minecraft_command(self, sid: str, data: dict) -> None:
        """Send a raw command to the bot (for direct control/debugging).

        data: {"action": "goto", "params": {"x": 10, "y": 64, "z": 20}}
        """
        try:
            bridge = get_bridge()
            if bridge is None or not bridge.is_running:
                await self.sio.emit(
                    "minecraft:command_result",
                    {"status": "error", "error": "Bot not running"},
                    to=sid,
                )
                return

            action = data.get("action", "status")
            params = data.get("params", {})
            timeout = data.get("timeout", 60)

            result = await bridge.send_command(action, params, timeout=timeout)
            await self.sio.emit(
                "minecraft:command_result",
                {"action": action, "result": result},
                to=sid,
            )
        except Exception as e:
            logger.error(f"[Minecraft] Command failed: {e}")
            await self.sio.emit(
                "minecraft:command_result",
                {"status": "error", "error": str(e)},
                to=sid,
            )
