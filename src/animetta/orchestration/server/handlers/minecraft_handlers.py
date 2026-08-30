"""
Minecraft bot control handlers.

Manages the mc-mcp lifecycle via Socket.IO events.
Follows the same pattern as BilibiliHandlers: frontend emits events,
backend starts/stops the service and reports status back.
"""

from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from ....tools.minecraft.core import tools as mc_tools
from ....tools.minecraft.core.bridge import MinecraftMcpBridge, get_bridge
from ....tools.minecraft.core.config import MinecraftConfig
from ....tools.minecraft.core.tools import init_bridge
from ...socket_events import EVENTS

if TYPE_CHECKING:
    from socketio import AsyncServer

    from animetta.services.livestream_narration import BroadcastNarrationDirector


TRUSTED_MINECRAFT_ROOM = "minecraft:trusted"


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

    def __init__(
        self,
        sio: "AsyncServer",
        director: "BroadcastNarrationDirector | None" = None,
    ):
        self.sio = sio
        self._director = director
        mc_tools.set_minecraft_event_emit(self._emit_transition)

    async def _emit_transition(self, payload: dict[str, Any]) -> None:
        if payload.get("event") == "minecraft.presentation.configured":
            mode = payload.get("mode")
            if self._director is not None and mode in {"off", "visual_only", "full"}:
                replay_limit = payload.get("replay_limit")
                self._director.configure(
                    mode,
                    replay_limit=(
                        replay_limit
                        if isinstance(replay_limit, int) and not isinstance(replay_limit, bool)
                        else None
                    ),
                )
            logger.info(
                "[Minecraft] presentation configured: mode={} profile={}",
                mode,
                payload.get("profile"),
            )
            return
        if payload.get("event") == "minecraft.activity.projection":
            if self._director is not None:
                bridge = get_bridge()
                if bridge is not None:
                    self._director.configure(
                        bridge.active_presentation_mode,
                        replay_limit=bridge.config.presentation.replay_limit,
                    )
                await self._director.submit(payload)
            else:
                await self.sio.emit(EVENTS["minecraft"]["activity_projection"]["name"], payload)
            return
        event_key = {
            "minecraft.skill.trust": "skill_trust",
            "minecraft.mission.projection": "mission_projection",
            "minecraft.objective.projection": "objective_projection",
            "minecraft.proposal.projection": "proposal_projection",
            "minecraft.discovery.projection": "discovery_projection",
            "minecraft.skill_validation.projection": "skill_validation",
            "minecraft.advancement.projection": "advancement_projection",
            "minecraft.stage.projection": "stage_projection",
        }.get(str(payload.get("event")), "command_transition")
        await self.sio.emit(
            EVENTS["minecraft"][event_key]["name"],
            payload,
            to=TRUSTED_MINECRAFT_ROOM,
        )

    async def replay_public(self, sid: str) -> None:
        if self._director is None:
            return
        try:
            page = await mc_tools.read_minecraft_public_activity_replay(
                limit=self._director.replay_limit
            )
        except RuntimeError:
            await self._director.replay(sid)
            return
        await self._director.replay_persisted(
            [event.model_dump(mode="json") for event in page.events],
            sid,
        )

    def _setup_viewer_callback(self, bridge: MinecraftMcpBridge) -> None:
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

    async def on_minecraft_connect(self, sid: str, data: dict) -> None:
        """Connect the configured mc-mcp profile and assemble the Anima control plane."""
        try:
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
            mc_cfg_dict["enabled"] = True
            config = MinecraftConfig(**mc_cfg_dict)
            if self._director is not None:
                self._director.configure(
                    config.presentation.effective_mode,
                    replay_limit=config.presentation.replay_limit,
                )
            init_bridge(config.model_dump())
            bridge = get_bridge()
            if bridge is None:
                raise RuntimeError("Minecraft MCP client initialization failed")
            self._setup_viewer_callback(bridge)
            payload = data if isinstance(data, dict) else {}
            result = await mc_tools.manage_minecraft_connection(
                "connect",
                request_id=str(payload.get("request_id") or f"socket:{sid}:connect"),
                profile=payload.get("profile"),
                event_emit=self._emit_transition,
            )
            if self._director is not None:
                self._director.configure(
                    bridge.active_presentation_mode,
                    replay_limit=bridge.config.presentation.replay_limit,
                )
            await self.sio.emit(EVENTS["minecraft"]["status"]["name"], result, to=sid)
        except Exception as e:
            logger.error(f"[Minecraft] Failed to connect: {e}")
            await self.sio.emit(
                EVENTS["minecraft"]["status"]["name"],
                {"state": "error", "error": str(e)},
                to=sid,
            )

    async def on_minecraft_status(self, sid: str, data: dict) -> None:
        await self._connection_action(sid, data, "status")

    async def on_minecraft_disconnect(self, sid: str, data: dict) -> None:
        await self._connection_action(sid, data, "disconnect")

    async def on_minecraft_shutdown(self, sid: str, data: dict) -> None:
        await self._connection_action(sid, data, "shutdown")

    async def _connection_action(
        self,
        sid: str,
        data: dict,
        operation: Literal["status", "disconnect", "shutdown"],
    ) -> None:
        try:
            payload = data if isinstance(data, dict) else {}
            result = await mc_tools.manage_minecraft_connection(
                operation,
                request_id=str(payload.get("request_id") or f"socket:{sid}:{operation}"),
            )
            await self.sio.emit(EVENTS["minecraft"]["status"]["name"], result, to=sid)
        except Exception as e:
            logger.error(f"[Minecraft] {operation} failed: {e}")
            await self.sio.emit(
                EVENTS["minecraft"]["status"]["name"],
                {"state": "error", "error": str(e)},
                to=sid,
            )

    async def on_minecraft_reattach_viewer(self, sid: str, data: dict) -> None:
        """Ask mc-mcp's viewer controller to retry automatic attachment."""
        try:
            payload = data if isinstance(data, dict) else {}
            result = await mc_tools.manage_minecraft_connection(
                "reattach_viewer",
                request_id=str(payload.get("request_id") or f"socket:{sid}:reattach"),
            )
            await self.sio.emit(
                EVENTS["minecraft"]["viewer_status"]["name"],
                project_viewer_status("client_viewer_status", result.get("viewer", {})),
                to=sid,
            )
        except Exception as e:
            logger.error(f"[Minecraft] Viewer reattach failed: {e}")
            await self.sio.emit(
                EVENTS["minecraft"]["viewer_status"]["name"],
                {"status": "error", "error": str(e)},
                to=sid,
            )
