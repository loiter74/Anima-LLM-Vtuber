"""
Minecraft bot control handlers.

Manages the MinecraftBridge lifecycle (start/stop) via Socket.IO events.
Follows the same pattern as BilibiliHandlers: frontend emits events,
backend starts/stops the service and reports status back.
"""

from typing import TYPE_CHECKING, Any

from loguru import logger

from ....tools.minecraft.core import tools as mc_tools
from ....tools.minecraft.core.bridge import MinecraftBridge, get_bridge
from ....tools.minecraft.core.config import MinecraftConfig
from ....tools.minecraft.core.state_collector import StateCollector
from ....tools.minecraft.core.tools import cleanup_bridge, init_bridge
from ...socket_events import EVENTS

if TYPE_CHECKING:
    from socketio import AsyncServer


_VIEWER_BINDING_STATES = frozenset({"disabled", "waiting", "attaching", "following", "degraded"})
_VIEWER_REASONS = frozenset(
    {
        "disabled",
        "viewer_offline",
        "viewer_joined",
        "bot_spawn",
        "bot_respawn",
        "dimension_change",
        "manual_retry",
        "periodic_check",
        "confirmation_timeout",
        "confirmation_rejected",
        "command_failed",
        "closed",
        "config_missing",
        "unknown",
    }
)
_LEGACY_STATUS_BY_BINDING = {
    "disabled": "waiting",
    "waiting": "waiting",
    "attaching": "waiting",
    "following": "joined",
    "degraded": "error",
}


def _safe_nonnegative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if not isinstance(value, (int, float, str, bytes, bytearray)):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _safe_viewer_text(value: object, *, default: str = "") -> str:
    if not isinstance(value, str):
        return default
    return value[:64]


def project_viewer_status(event_type: str, payload: dict[str, Any] | object) -> dict[str, Any]:
    """Project runtime viewer events onto the safe V2 and legacy socket contract."""
    if event_type != "client_viewer_status" or not isinstance(payload, dict):
        joined = event_type == "viewer_joined"
        return {
            "schema_version": 2,
            "status": "joined" if joined else "left",
            "binding_state": "following" if joined else "waiting",
            "confirmed": joined,
            "username": _safe_viewer_text(payload),
            "mode": "spectator",
            "target": "AnimettaBot",
            "attempt": 0,
            "reason": "viewer_joined" if joined else "viewer_offline",
        }

    raw_state = payload.get("binding_state", payload.get("state", "waiting"))
    binding_state = raw_state if raw_state in _VIEWER_BINDING_STATES else "degraded"
    raw_reason = payload.get("reason", "unknown")
    reason = raw_reason if raw_reason in _VIEWER_REASONS else "unknown"
    confirmed = binding_state == "following" and payload.get("confirmed") is True
    data: dict[str, Any] = {
        "schema_version": 2,
        "status": _LEGACY_STATUS_BY_BINDING[binding_state],
        "binding_state": binding_state,
        "confirmed": confirmed,
        "username": _safe_viewer_text(payload.get("username")),
        "mode": "spectator",
        "target": _safe_viewer_text(payload.get("target"), default="AnimettaBot"),
        "attempt": _safe_nonnegative_int(payload.get("attempt")),
        "reason": reason,
    }
    if "retry_in_ms" in payload:
        data["retry_in_ms"] = _safe_nonnegative_int(payload["retry_in_ms"])
    return data


class MinecraftHandlers:
    """Minecraft bot lifecycle handlers.

    Receives sio for emitting status events back to the frontend.
    Uses the global Minecraft bridge singleton (init_bridge / cleanup_bridge).
    """

    def __init__(self, sio: "AsyncServer"):
        self.sio = sio
        self._state_collector: StateCollector | None = None

    async def _configure_voyager(self, bridge: MinecraftBridge) -> bool:
        """Attach the Python control plane when the shared LLM is available."""
        from animetta.core.service_pool import ServicePool

        if not ServicePool._ready or ServicePool._llm is None:
            logger.warning(
                "[Minecraft] Shared LLM is unavailable; Voyager controller not configured"
            )
            return False
        await mc_tools.configure_voyager_controller(
            bridge,
            llm_service=ServicePool._llm,
        )
        logger.info("[Minecraft] Python Voyager controller configured")
        return True

    def _setup_viewer_callback(self, bridge: MinecraftBridge) -> None:
        """Register callback to forward viewer join/leave events to frontend."""

        def on_viewer_event(event_type: str, payload: dict[str, Any] | object) -> None:
            import asyncio

            data = project_viewer_status(event_type, payload)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self.sio.emit(
                        EVENTS["minecraft"]["viewer_status"]["name"],
                        data,
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
            # Load full minecraft config from tools.yaml (includes runtime path/entrypoint)
            from pathlib import Path

            import yaml

            config_path = (
                Path(__file__).parent.parent.parent.parent.parent.parent / "config" / "tools.yaml"
            )
            mc_cfg_dict: dict = {}
            if config_path.exists():
                with open(config_path, encoding="utf-8") as f:
                    tools_yaml = yaml.safe_load(f) or {}
                mc_cfg_dict = tools_yaml.get("minecraft", {}) or {}
            # Force enabled=True (frontend explicitly requested start)
            mc_cfg_dict["enabled"] = True
            config = MinecraftConfig(**mc_cfg_dict)
            logger.info(
                f"[Minecraft] Frontend requested start "
                f"(runtime={config.runtime.runtime_path or 'default'}, "
                f"entrypoint={config.runtime.entrypoint})"
            )

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
            await self._configure_voyager(bridge)

            # Start state collector for HUD + web dashboard
            collector = StateCollector(bridge, self.sio, interval=2.0)
            self._state_collector = collector
            mc_tools._state_collector = collector
            await collector.start()

            await self.sio.emit(
                EVENTS["minecraft"]["status"]["name"],
                {"connected": True, "username": config.bot.username},
                to=sid,
            )

            # If viewer is configured, emit initial waiting status
            if config.client_viewer.enabled:
                await self.sio.emit(
                    EVENTS["minecraft"]["viewer_status"]["name"],
                    project_viewer_status(
                        "client_viewer_status",
                        {
                            "binding_state": "waiting",
                            "confirmed": False,
                            "username": config.client_viewer.username,
                            "target": config.bot.username,
                            "attempt": 0,
                            "reason": "viewer_offline",
                        },
                    ),
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
                    EVENTS["minecraft"]["command_result"]["name"],
                    {"status": "error", "error": "Bot not running"},
                    to=sid,
                )
                return

            action = data.get("action", "status")
            params = data.get("params", {})
            timeout = data.get("timeout", 60)

            result = await bridge.send_command(action, params, timeout=timeout)
            await self.sio.emit(
                EVENTS["minecraft"]["command_result"]["name"],
                {"action": action, "result": result},
                to=sid,
            )
        except Exception as e:
            logger.error(f"[Minecraft] Command failed: {e}")
            await self.sio.emit(
                EVENTS["minecraft"]["command_result"]["name"],
                {"status": "error", "error": str(e)},
                to=sid,
            )
