"""
LangGraph Orchestrator

"""

from __future__ import annotations

import time as time_module
from typing import Any

from loguru import logger

from animetta.tracing.context import attach_trace_context, detach_trace_context

from .builder import create_default_graph
from .interrupt_handler import get_interrupt_handler
from .observability import get_observability
from .state import AgentState, create_initial_state
from .stats_handler import StatsCallbackHandler
from .tool_manager import ToolManager


class LangGraphOrchestrator:
    """LangGraph orchestrator"""

    _instances: dict[str, LangGraphOrchestrator] = {}

    def __init__(
        self,
        service_context: Any,
        socketio: Any,
        emotion_analyzer: Any | None = None,
        enable_tools: bool = False,
        enable_memory: bool = True,
        tools_config: dict[str, Any] | None = None,
    ):
        self.service_context = service_context
        self.socketio = socketio
        self.emotion_analyzer = emotion_analyzer
        self.enable_tools = enable_tools
        self.enable_memory = enable_memory
        self.tools_config = tools_config or {}

        self.session_id = getattr(service_context, "session_id", "unknown")

        self.graph = None
        self._is_running = False
        self._processing_audio = False  # guard against concurrent audio processing

        # Initialize tool manager
        self.tool_manager: ToolManager | None = None

        # Build LangGraph config (passed to nodes via config parameter)
        self._langgraph_config = {
            "configurable": {
                "service_context": service_context,
                "socketio": socketio,
                "emotion_analyzer": emotion_analyzer,
                "thread_id": self.session_id,
            }
        }

        # Initialize observability
        obs = get_observability()
        if not obs._initialized:
            obs.initialize()

        self._callbacks = obs.callbacks
        if self._callbacks:
            logger.info(f"[{self.session_id}] [LangGraph] Observability callbacks: {len(self._callbacks)}")

        # Stats handler
        self._stats_handler = StatsCallbackHandler()
        if self._callbacks:
            self._callbacks.append(self._stats_handler)
        else:
            self._callbacks = [self._stats_handler]
        logger.info(f"[{self.session_id}] [LangGraph] Stats handler injected")

        logger.info(f"[{self.session_id}] [LangGraph] Orchestrator initialized")

    async def start(self) -> None:
        """Start the orchestrator"""
        if self._is_running:
            logger.warning(f"[{self.session_id}] [LangGraph] Orchestrator is already running")
            return

        logger.info(f"[{self.session_id}] [LangGraph] Building state graph...")
        logger.info(f"[{self.session_id}] [LangGraph] self.enable_tools={self.enable_tools}")

        try:
            # Load tools
            if self.enable_tools:
                logger.info(f"[{self.session_id}] [LangGraph] Tools enabled, loading...")
                await self._load_tools()
            else:
                logger.warning(f"[{self.session_id}] [LangGraph] Tools not enabled")

            # Create state graph
            self.graph = create_default_graph(
                enable_memory=False,
                enable_tools=self.enable_tools,
                tools=self.tool_manager.core.tools if self.tool_manager else None,
                tools_map=self.tool_manager.core.tools_map if self.tool_manager else None,
            )

            self._is_running = True
            logger.info(f"[{self.session_id}] [LangGraph] State graph started — _is_running={self._is_running}")

        except Exception as e:
            logger.error(f"[{self.session_id}] [LangGraph] Start failed: {e}")
            raise

    async def _load_tools(self) -> None:
        """Load tools"""
        self.tool_manager = ToolManager(self.session_id, self.service_context)
        success = await self.tool_manager.load_tools(self.tools_config)

        if success:
            # Update LangGraph config
            self._langgraph_config["configurable"].update(self.tool_manager.get_config())
            logger.info(f"[{self.session_id}] [LangGraph] Tool config added to LangGraph config")
        else:
            self.enable_tools = False
            logger.warning(f"[{self.session_id}] [LangGraph] Tool loading failed, tool calls disabled")

    async def stop(self) -> None:
        """Stop the orchestrator"""
        if not self._is_running:
            return

        if self.tool_manager:
            await self.tool_manager.cleanup()

        self._is_running = False
        logger.info(f"[{self.session_id}] [LangGraph] Orchestrator stopped")

    async def process_text(
        self,
        text: str,
        user_id: str | None = None,
        user_name: str | None = None,
        channel_id: str | None = None,
        **metadata,
    ) -> dict[str, Any]:
        """Process text input"""
        if not self._is_running:
            return {"error": "Orchestrator not started"}

        logger.info(f"[{self.session_id}] [LangGraph] Processing text input: {text[:50]}...")

        # Clear interrupt signal
        get_interrupt_handler().clear_interrupt(self.session_id)

        try:
            initial_state = self._create_initial_state(
                input_type="text",
                user_text=text,
                channel_id=channel_id,
                user_id=user_id,
                user_name=user_name,
                metadata=metadata,
            )
            final_state = await self._run_graph(initial_state)
            return self._clean_result(final_state)

        except Exception as e:
            logger.error(f"[{self.session_id}] [LangGraph] Text processing failed: {e}")
            return {"error": str(e), "response_text": ""}

    async def process_audio(
        self,
        audio_data: bytes,
        user_id: str | None = None,
        user_name: str | None = None,
        channel_id: str | None = None,
        **metadata,
    ) -> dict[str, Any]:
        """Process audio input"""
        if not self._is_running:
            return {"error": "Orchestrator not started"}

        if self._processing_audio:
            logger.debug(f"[{self.session_id}] [LangGraph] Audio already processing, skipping")
            return {"error": "Audio already processing"}

        self._processing_audio = True
        logger.info(f"[{self.session_id}] [LangGraph] Processing audio input: {len(audio_data)} bytes")

        get_interrupt_handler().clear_interrupt(self.session_id)

        try:
            initial_state = self._create_initial_state(
                input_type="audio",
                raw_audio=audio_data,
                channel_id=channel_id,
                user_id=user_id,
                user_name=user_name,
                metadata=metadata,
            )

            final_state = await self._run_graph(initial_state)
            result = self._clean_result(final_state)
            return result

        except Exception as e:
            logger.error(f"[{self.session_id}] [LangGraph] Audio processing failed: {e}")
            return {"error": str(e), "response_text": ""}
        finally:
            self._processing_audio = False

    def _create_initial_state(
        self,
        input_type: str,
        user_text: str = "",
        raw_audio: bytes | None = None,
        channel_id: str | None = None,
        user_id: str | None = None,
        user_name: str | None = None,
        metadata: dict | None = None,
    ) -> AgentState:
        """Create initial state"""
        initial_state = create_initial_state(
            session_id=self.session_id,
            input_type=input_type,
            user_text=user_text,
            raw_audio=raw_audio,
            persona=self._get_persona_dict(),
            system_prompt=self._get_system_prompt(),
            channel_id=channel_id,
            user_id=user_id,
            user_name=user_name,
        )

        if metadata:
            initial_state["metadata"] = metadata

        return initial_state

    async def _run_graph(self, initial_state: AgentState) -> dict[str, Any]:
        """Run the state graph, passing service context through LangGraph config"""
        # Start trace
        input_type = initial_state.get("input_type", "text")
        user_text = initial_state.get("user_text", "")
        trace_id = self._stats_handler.start_trace(self.session_id, input_type, user_text)

        # Attach OTel context so TracingProxy spans inherit this trace_id
        _token = attach_trace_context(trace_id)

        run_config = dict(self._langgraph_config)
        callbacks = self._callbacks or get_observability().callbacks
        if callbacks:
            run_config["callbacks"] = callbacks

        logger.info(f"[{self.session_id}] [LangGraph] _run_graph starting — input_type={input_type}, user_text={user_text[:50]}...")
        t_start = time_module.perf_counter()

        try:
            result = await self.graph.ainvoke(initial_state, config=run_config)
            duration_ms = (time_module.perf_counter() - t_start) * 1000
            logger.info(f"[{self.session_id}] [LangGraph] _run_graph completed in {duration_ms:.0f}ms")
            self._stats_handler.finish_trace(status="success")
            return result
        except Exception as e:
            duration_ms = (time_module.perf_counter() - t_start) * 1000
            logger.error(f"[{self.session_id}] [LangGraph] _run_graph failed after {duration_ms:.0f}ms: {e}")
            self._stats_handler.finish_trace(status="error", error_msg=str(e)[:500])
            raise
        finally:
            detach_trace_context(_token)

    def _clean_result(self, final_state: dict[str, Any]) -> dict[str, Any]:
        """Clean up return value"""
        return {
            "response_text": final_state.get("response_text", ""),
            "response_chunks": final_state.get("response_chunks", []),
            "tts_audio": final_state.get("tts_audio"),
            "emotion": final_state.get("emotion"),
            "error": final_state.get("error"),
        }

    def _get_system_prompt(self) -> str | None:
        """Get system prompt from persona config."""
        if self.service_context and self.service_context.core.config:
            persona = self.service_context.core.config.get_persona()
            if persona:
                return persona.build_system_prompt()
        return None

    def _get_persona_dict(self) -> dict[str, Any] | None:
        """Get persona config dict"""
        if self.service_context and self.service_context.core.config:
            persona = self.service_context.core.config.get_persona()
            if persona:
                result = {
                    "name": persona.name,
                    "role": persona.role,
                    "identity": persona.identity,
                    "personality": persona.personality.dict() if hasattr(persona.personality, "dict") else {},
                    "behavior": persona.behavior.dict() if hasattr(persona.behavior, "dict") else {},
                    "speaking_style": persona.speaking_style,
                }
                # Include MBTI profile if configured
                if persona.personality.mbti:
                    result["mbti"] = persona.personality.mbti.dict() if hasattr(persona.personality.mbti, "dict") else {}
                return result
        return {}

    @classmethod
    async def create(
        cls,
        session_id: str,
        service_context: Any,
        socketio: Any,
        emotion_analyzer: Any | None = None,
        enable_tools: bool = False,
        enable_memory: bool = True,
        tools_config: dict[str, Any] | None = None,
    ) -> LangGraphOrchestrator:
        """Create orchestrator instance"""
        orchestrator = LangGraphOrchestrator(
            service_context=service_context,
            socketio=socketio,
            emotion_analyzer=emotion_analyzer,
            enable_tools=enable_tools,
            enable_memory=enable_memory,
            tools_config=tools_config,
        )

        await orchestrator.start()
        cls._instances[session_id] = orchestrator
        return orchestrator

    @classmethod
    def get(cls, session_id: str) -> LangGraphOrchestrator | None:
        return cls._instances.get(session_id)

    @classmethod
    async def remove(cls, session_id: str) -> None:
        orchestrator = cls._instances.pop(session_id, None)
        if orchestrator:
            await orchestrator.stop()

    @classmethod
    async def clear_all(cls) -> None:
        for session_id, orchestrator in cls._instances.items():
            await orchestrator.stop()
        cls._instances.clear()
