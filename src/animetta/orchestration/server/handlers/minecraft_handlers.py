"""
Minecraft bot control handlers.

Manages the MinecraftBridge lifecycle (start/stop) via Socket.IO events.
Follows the same pattern as BilibiliHandlers: frontend emits events,
backend starts/stops the service and reports status back.
"""

from typing import TYPE_CHECKING

from loguru import logger

from ...socket_events import EVENTS

if TYPE_CHECKING:
    from socketio import AsyncServer


class MinecraftHandlers:
    """Minecraft bot lifecycle handlers.

    Receives sio for emitting status events back to the frontend.
    Uses the global Minecraft bridge singleton (init_bridge / cleanup_bridge).
    """

    def __init__(self, sio: "AsyncServer"):
        self.sio = sio

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

            await bridge.start()
            logger.info("[Minecraft] Bot started successfully")
            await self.sio.emit(
                EVENTS["minecraft"]["status"]["name"],
                {"connected": True, "username": config.bot.username},
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
