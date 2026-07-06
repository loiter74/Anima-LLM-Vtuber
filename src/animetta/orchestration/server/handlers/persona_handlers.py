"""
Persona event handlers — persona switching, personality mode.
"""

from typing import TYPE_CHECKING

from loguru import logger

from animetta.config.persona import PersonaConfig, list_available_personas

from ...socket_events import EVENTS
from .base_handler import BaseSocketHandler

if TYPE_CHECKING:
    from socketio import AsyncServer

    from ..desktop import DesktopClientManager
    from ..live2d import Live2DManager
    from ..session import SessionManager

class PersonaHandlers(BaseSocketHandler):
    """Persona and personality mode event handlers.

    Inherits shared infrastructure from BaseSocketHandler.
    """

    def __init__(
        self,
        sio: "AsyncServer",
        session_manager: "SessionManager",
        desktop_manager: "DesktopClientManager",
        live2d_manager: "Live2DManager",
        base: "BaseSocketHandler | None" = None,
    ):
        super().__init__(sio, session_manager, desktop_manager, live2d_manager)
        self._base = base

    @property
    def global_config(self):
        """Get global_config from base handler if available."""
        logger.debug(
            "[PersonaHandlers] global_config requested: has_base={}, "
            "base_has_config={}, local_has_config={}",
            self._base is not None,
            bool(self._base and self._base.global_config),
            self._global_config is not None,
        )
        if self._base and self._base.global_config:
            return self._base.global_config
        return self._global_config

    @global_config.setter
    def global_config(self, value):
        logger.debug(
            "[PersonaHandlers] global_config updated: has_config={}",
            value is not None,
        )
        self._global_config = value

    # ── Persona Runtime Switching ──────────────────────────────────────

    async def on_get_available_personas(self, sid: str, data: dict) -> dict:
        """获取可用的人设列表"""
        try:
            personas = list_available_personas()

            # Get current persona's MBTI data
            mbti_data = None
            current_persona_name = None
            try:
                active_config = self.global_config
                logger.debug(
                    "[{}] on_get_available_personas: has_config={}",
                    sid,
                    active_config is not None,
                )
                if active_config:
                    current_persona_name = active_config.persona
                    logger.info(f"[{sid}] Loading persona: {current_persona_name}")
                    if hasattr(active_config, "get_persona"):
                        current_persona = active_config.get_persona()
                    else:
                        current_persona = PersonaConfig.load(current_persona_name)
                    if current_persona and current_persona.personality and current_persona.personality.mbti:
                        mbti = current_persona.personality.mbti
                        mbti_data = {
                            "type": mbti.type,
                            "dimensions": {
                                "ei": mbti.dimensions.ei,
                                "sn": mbti.dimensions.sn,
                                "tf": mbti.dimensions.tf,
                                "jp": mbti.dimensions.jp,
                            },
                            "description": mbti.description,
                        }
                        logger.info(f"[{sid}] MBTI data: {mbti_data}")
                    else:
                        logger.info(f"[{sid}] No MBTI data found in persona")
                else:
                    logger.info(f"[{sid}] global_config is None")
            except Exception as e:
                logger.error(f"[{sid}] 获取当前人格MBTI数据失败: {e}", exc_info=True)

            return {
                "personas": personas,
                "current_persona": current_persona_name,
                "mbti": mbti_data,
            }
        except Exception as e:
            logger.error(f"[{sid}] 获取人设列表失败: {e}")
            return {"personas": ["default"], "error": str(e)}

    async def on_set_persona(self, sid: str, data: dict) -> None:
        """运行时切换人设"""
        persona_name = data.get("persona_name", "")
        if not persona_name:
            logger.warning(f"[{sid}] 切换人设失败: 人设名称为空")
            await self.sio.emit(
                EVENTS["system"]["error"]["name"],
                {"type": "error", "message": "persona_name is required"},
                to=sid,
            )
            return

        logger.info(f"[{sid}] 切换人设: {persona_name}")

        try:
            ctx = self.session_manager.get_context(sid)
            if not ctx:
                await self.sio.emit(
                    EVENTS["system"]["error"]["name"],
                    {"type": "error", "message": "会话未初始化"},
                    to=sid,
                )
                return

            new_persona = PersonaConfig.load(persona_name)
            if not new_persona:
                await self.sio.emit(
                    EVENTS["system"]["error"]["name"],
                    {"type": "error", "message": f"无法加载人设: {persona_name}"},
                    to=sid,
                )
                return

            if self.global_config:
                self.global_config.persona = persona_name
                self.global_config._persona = None  # Invalidate cache

            ctx_config = getattr(ctx, "config", None)
            if ctx_config is None:
                legacy_core = getattr(ctx, "core", None)
                ctx_config = getattr(legacy_core, "config", None)

            if ctx.llm_engine and ctx_config:
                live2d_prompt = None
                try:
                    from animetta.avatar.prompts import EmotionPromptBuilder
                    from animetta.config.live2d import get_live2d_config

                    live2d_cfg = get_live2d_config()
                    if live2d_cfg and live2d_cfg.enabled:
                        builder = EmotionPromptBuilder.from_config(
                            {"valid_emotions": live2d_cfg.valid_emotions}
                        )
                        live2d_prompt = builder.build_prompt()
                except Exception as e:
                    logger.debug(f"[PersonaHandlers] Failed to build Live2D emotion prompt: {e}")

                new_system_prompt = ctx_config.get_system_prompt(
                    live2d_prompt=live2d_prompt
                )
                ctx.llm_engine.set_system_prompt(new_system_prompt)
                logger.info(f"[{sid}] 已更新 LLM 系统提示词")

            orchestrator = self.session_manager.get_orchestrator(sid)
            if orchestrator:
                logger.info(f"[{sid}] 编排器已感知人设变更")

            logger.info(f"[{sid}] 人设切换完成: {persona_name}")

            # Build MBTI data for frontend
            mbti_data = None
            if new_persona.personality and new_persona.personality.mbti:
                mbti = new_persona.personality.mbti
                mbti_data = {
                    "type": mbti.type,
                    "dimensions": {
                        "ei": mbti.dimensions.ei,
                        "sn": mbti.dimensions.sn,
                        "tf": mbti.dimensions.tf,
                        "jp": mbti.dimensions.jp,
                    },
                    "description": mbti.description,
                }

            await self.sio.emit(
                EVENTS["persona"]["updated"]["name"],
                {"persona_name": persona_name, "mbti": mbti_data},
                to=sid,
            )

        except Exception as e:
            logger.error(f"[{sid}] 切换人设失败: {e}", exc_info=True)
            await self.sio.emit(
                EVENTS["system"]["error"]["name"], {"type": "error", "message": str(e)}, to=sid
            )

    async def on_set_personality_mode(self, sid: str, data: dict) -> None:
        """设置个性模式（运行时切换）"""
        mode = data.get("mode", "")
        if not mode:
            logger.warning(f"[{sid}] 设置个性模式失败: mode 为空")
            await self.sio.emit(
                EVENTS["system"]["error"]["name"], {"type": "error", "message": "mode is required"}, to=sid
            )
            return

        logger.info(f"[{sid}] 设置个性模式: {mode}")

        try:
            orchestrator = self.session_manager.get_orchestrator(sid)

            if orchestrator:
                if not hasattr(orchestrator, "_personality_mode"):
                    orchestrator._personality_mode = {}
                orchestrator._personality_mode["mode"] = mode
                logger.info(f"[{sid}] 编排器已更新个性模式")

            await self.sio.emit(EVENTS["persona"]["personality_updated"]["name"], {"mode": mode}, to=sid)
            logger.info(f"[{sid}] 个性模式已设置: {mode}")

        except Exception as e:
            logger.error(f"[{sid}] 设置个性模式失败: {e}", exc_info=True)
            await self.sio.emit(
                EVENTS["system"]["error"]["name"], {"type": "error", "message": str(e)}, to=sid
            )
