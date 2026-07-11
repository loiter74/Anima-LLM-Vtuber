"""
Session management
Manages client session lifecycle and resources
Uses LangGraph orchestrator
"""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

from animetta.core.service_pool import ServicePool

from ...core.service_context import ServiceContext


class SessionManager:
    """
    Session manager

    Responsibilities:
    1. Manage ServiceContext for all client sessions
    2. Manage LangGraphOrchestrator for all sessions
    3. Create and destroy session resources
    """

    def __init__(self, model_manager=None):
        # Store ServiceContext per session
        # Key: session_id, Value: ServiceContext instance
        self.contexts: dict[str, ServiceContext] = {}
        self.model_manager = model_manager

        # Store orchestrator per session
        # Key: session_id, Value: LangGraphOrchestrator instance
        self.orchestrators: dict[str, Any] = {}
        self._orchestrator_lock = asyncio.Lock()

        # Store audio processor per session
        # Key: session_id, Value: AudioProcessor instance
        self.audio_processors: dict[str, Any] = {}

    # ========================================
    # Context management
    # ========================================

    async def get_or_create_context(
        self,
        sid: str,
        config,
        websocket_send: Callable
    ) -> ServiceContext:
        """
        Get or create the ServiceContext for a given session

        Args:
            sid: session id
            config: Application config
            websocket_send: WebSocket send function

        Returns:
            ServiceContext: The service context for this session
        """
        if sid not in self.contexts:
            logger.info(f"[{sid}] Creating new ServiceContext")
            ctx = ServiceContext(model_manager=self.model_manager)
            ctx.session_id = sid
            ctx.send_text = websocket_send

            # Use ServicePool when available — skips LLM/TTS/ASR init
            pool = ServicePool.get_context()
            if pool:
                logger.info(f"[{sid}] Using pooled engines (LLM/TTS/ASR)")
                await ctx.load_cache(config=config, **pool)
                await ctx.init_vad(config.vad)
                await ctx.init_memory()
                await ctx.init_emotion_analyzer(config)
            else:
                logger.info(f"[{sid}] Pool not available, full init")
                await ctx.load_from_config(config)

            self.contexts[sid] = ctx
            logger.info(f"Created new ServiceContext for session {sid}")

        return self.contexts[sid]

    def get_context(self, sid: str) -> ServiceContext | None:
        """Get session context"""
        return self.contexts.get(sid)

    # ========================================
    # Orchestrator management
    # ========================================

    async def get_or_create_orchestrator(
        self,
        sid: str,
        ctx: ServiceContext,
        websocket_send: Callable,
        live2d_config,
        socketio=None,
    ):
        """
        Get or create the LangGraph orchestrator for a given session

        Args:
            sid: session id
            ctx: ServiceContext
            websocket_send: WebSocket send function
            live2d_config: Live2D config

        Returns:
            LangGraphOrchestrator: Orchestrator instance
        """
        async with self._orchestrator_lock:
            if sid in self.orchestrators:
                return self.orchestrators[sid]
            logger.info(f"[{sid}] Creating new LangGraphOrchestrator")

            # Load tool settings from config
            tools_config = await self._load_tools_config()

            # Create LangGraph Orchestrator
            from ..graph.orchestrator import LangGraphOrchestrator

            # Ensure enable_tools is correctly passed
            enable_tools = tools_config.get("enable_tools", False)
            system = getattr(getattr(ctx, "config", None), "system", None)
            if getattr(system, "runtime_profile", None) == "golden":
                enable_tools = False
            raw_config = tools_config.get("config", tools_config)
            config_keys = list(raw_config.keys()) if isinstance(raw_config, dict) else []
            logger.info(
                "[{}] Tool config status: enable_tools={}, config_keys={}",
                sid,
                bool(enable_tools),
                config_keys,
            )

            orchestrator = await LangGraphOrchestrator.create(
                session_id=sid,
                service_context=ctx,
                socketio=socketio,  # Socket.IO instance for sending messages
                emotion_analyzer=ctx.emotion_analyzer if hasattr(ctx, 'emotion_analyzer') else None,
                enable_tools=enable_tools,
                enable_memory=True,
                tools_config=tools_config.get("config", tools_config),
            )

            logger.info(f"[{sid}] LangGraphOrchestrator created")
            self.orchestrators[sid] = orchestrator
            logger.info(f"Created new LangGraphOrchestrator for session {sid}")

        return self.orchestrators[sid]

    async def _load_tools_config(self) -> dict[str, Any]:
        """Load tools configuration"""
        try:
            import yaml
            # Fix path: from src/anima/orchestration/server/session.py to project root config/tools.yaml
            # __file__ = .../src/anima/orchestration/server/session.py
            # Need: .../config/tools.yaml
            # So need to go up 5 levels to project root (orchestration/server -> orchestration -> anima -> src -> project_root)
            config_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "tools.yaml"

            logger.info(f"[_load_tools_config] Config file path: {config_path}")
            logger.info(f"[_load_tools_config] File exists: {config_path.exists()}")

            if config_path.exists():
                with open(config_path, encoding='utf-8') as f:
                    tools_config = yaml.safe_load(f)

                    # Verbose debug logging
                    top_level_keys = (
                        list(tools_config.keys())
                        if isinstance(tools_config, dict)
                        else []
                    )
                    logger.info(
                        "[_load_tools_config] Raw YAML parse result type: {}",
                        type(tools_config),
                    )
                    logger.info(
                        "[_load_tools_config] YAML top-level keys: {}",
                        top_level_keys,
                    )

                    # Check if tools are explicitly enabled - fix config path
                    tool_settings = tools_config.get("tool_settings", {})
                    logger.info(
                        "[_load_tools_config] tool_settings type: {}, keys={}",
                        type(tool_settings),
                        list(tool_settings.keys()) if isinstance(tool_settings, dict) else [],
                    )

                    enable_tools = tool_settings.get("enable_tools", False)
                    logger.info(
                        "[_load_tools_config] enable_tools={}, type={}",
                        bool(enable_tools),
                        type(enable_tools),
                    )

                    logger.info(f"[_load_tools_config] Tool calls {'enabled' if enable_tools else 'disabled'}")

                    result = {
                        "enable_tools": enable_tools,
                        "config": tools_config,
                    }
                    logger.info(f"[_load_tools_config] Returning enable_tools: {result['enable_tools']}")
                    return result
            else:
                logger.info(f"Tools config file does not exist: {config_path}")
                return {"enable_tools": False, "config": {}}

        except Exception as e:
            logger.exception(f"[_load_tools_config] Failed to load tools config: {e}")
            return {"enable_tools": False, "config": {}}

    def get_orchestrator(self, sid: str) -> Any | None:
        """Get session orchestrator"""
        return self.orchestrators.get(sid)

    # ========================================
    # Cleanup methods
    # ========================================

    async def cleanup_session(self, sid: str) -> None:
        """
        Clean up all resources for a given session

        Args:
            sid: session id
        """
        # Stop orchestrator
        if sid in self.orchestrators:
            orchestrator = self.orchestrators[sid]
            if hasattr(orchestrator, 'stop'):
                await orchestrator.stop()
            del self.orchestrators[sid]

        # Clean up audio processor
        if sid in self.audio_processors:
            processor = self.audio_processors[sid]
            if hasattr(processor, 'reset'):
                processor.reset()
            del self.audio_processors[sid]

        # Clean up context
        if sid in self.contexts:
            ctx = self.contexts[sid]
            await ctx.close()
            del self.contexts[sid]
            logger.info(f"Cleaned up all resources for session {sid}")

    async def cleanup_all(self) -> None:
        """Clean up all sessions"""
        logger.info("Cleaning up all sessions...")

        # Stop all orchestrators
        for sid, orchestrator in list(self.orchestrators.items()):
            try:
                if hasattr(orchestrator, 'stop'):
                    await orchestrator.stop()
                logger.debug(f"[{sid}] Orchestrator stopped")
            except Exception as e:
                logger.error(f"[{sid}] Error stopping orchestrator: {e}")
        self.orchestrators.clear()

        # Close all contexts
        for sid, ctx in list(self.contexts.items()):
            try:
                await ctx.close()
                logger.debug(f"[{sid}] Context closed")
            except Exception as e:
                logger.error(f"[{sid}] Error closing context: {e}")
        # Clean up all audio processors
        for sid, processor in list(self.audio_processors.items()):
            try:
                if hasattr(processor, 'reset'):
                    processor.reset()
                logger.debug(f"[{sid}] AudioProcessor reset")
            except Exception as e:
                logger.error(f"[{sid}] Error resetting AudioProcessor: {e}")
        self.audio_processors.clear()

        self.contexts.clear()

        logger.info("All sessions cleaned up")


    def get_audio_processor(self, sid: str) -> Any | None:
        """Get session audio processor"""
        return self.audio_processors.get(sid)

    async def get_or_create_audio_processor(
        self,
        sid: str,
        ctx: ServiceContext,
    ):
        """
        Get or create an audio processor

        Args:
            sid: session id
            ctx: ServiceContext

        Returns:
            AudioProcessor: Audio processor instance
        """
        if sid not in self.audio_processors:
            from ...services.audio.simple_vad_processor import SimpleVADProcessor

            async def on_speech_end(audio_data):
                # When speech ends, call orchestrator to process audio
                orchestrator = self.get_orchestrator(sid)
                if orchestrator:
                    import numpy as np
                    # Convert to bytes
                    audio_bytes = (np.array(audio_data, dtype=np.float32) * 32768).astype(np.int16).tobytes()
                    await orchestrator.process_audio(audio_bytes)

            processor = SimpleVADProcessor(
                session_id=sid,
                vad_engine=ctx.vad_engine,
                on_speech_end=on_speech_end,
            )

            self.audio_processors[sid] = processor
            logger.info(f"[{sid}] AudioProcessor created")

        return self.audio_processors[sid]


    @property
    def session_count(self) -> int:
        """Get active session count"""
        return len(self.contexts)
