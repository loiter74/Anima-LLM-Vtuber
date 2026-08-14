"""
LangGraph Orchestrator

"""

from __future__ import annotations

import asyncio
import time as time_module
from typing import TYPE_CHECKING, Any, cast

from langchain_core.runnables import RunnableConfig
from loguru import logger

from animetta.core.message_filter import should_skip_llm
from animetta.observability.conversation import ConversationObserver
from animetta.observability.domain import PrivacyMode
from animetta.observability.ports import (
    NoOpObservationRecorder,
    ObservationRecorder,
)

from .builder import CompiledAgentGraph, create_default_graph
from .conversation_session import (
    ConversationSessionRegistry,
    resolve_conversation_scope,
)
from .interrupt_handler import get_interrupt_handler
from .observability import get_observability
from .state import AgentState, create_initial_state
from .tool_manager import ToolManager

if TYPE_CHECKING:
    from .tool_observation import ToolInvocationObserver


class LangGraphOrchestrator:
    """LangGraph orchestrator

    Per-session instances are owned by ``SessionManager.orchestrators`` (the
    real registry, cleaned up in ``cleanup_session``). This class deliberately
    does **not** keep its own class-level registry — an earlier ``_instances``
    dict was populated by ``create()`` but never read or evicted, which caused
    an unbounded memory leak across sessions.
    """

    def __init__(
        self,
        service_context: Any,
        socketio: Any,
        emotion_analyzer: Any | None = None,
        enable_tools: bool = False,
        enable_memory: bool = True,
        tools_config: dict[str, Any] | None = None,
        observation_recorder: ObservationRecorder | None = None,
        tool_manager: ToolManager | None = None,
        conversation_registry: ConversationSessionRegistry | None = None,
    ):
        self.service_context = service_context
        self.socketio = socketio
        self.emotion_analyzer = emotion_analyzer
        self.enable_tools = enable_tools
        self.enable_memory = enable_memory
        self.tools_config = tools_config or {}
        self.observation_recorder = observation_recorder or NoOpObservationRecorder()

        raw_session_id = getattr(service_context, "session_id", None)
        self.session_id = (
            raw_session_id if isinstance(raw_session_id, str) and raw_session_id else "unknown"
        )

        self.graph: CompiledAgentGraph | None = None
        self._is_running = False
        self._processing_audio = False  # guard against concurrent audio processing
        self.conversation_registry = conversation_registry or ConversationSessionRegistry()

        # Initialize tool manager
        self.tool_manager = tool_manager

        # Build LangGraph config (passed to nodes via config parameter)
        self._langgraph_config: dict[str, Any] = {
            "configurable": {
                "service_context": service_context,
                "socketio": socketio,
                "emotion_analyzer": emotion_analyzer,
                "thread_id": self.session_id,
                "observation_recorder": self.observation_recorder,
            }
        }

        # Initialize observability
        obs = get_observability()
        if not obs._initialized:
            obs.initialize()

        self._callbacks = obs.callbacks
        if self._callbacks:
            logger.info(
                f"[{self.session_id}] [LangGraph] Observability callbacks: {len(self._callbacks)}"
            )

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
                tools=self.tool_manager.tools if self.tool_manager else None,
                tools_map=self.tool_manager.tools_map if self.tool_manager else None,
                golden_profile=self._is_golden_profile(),
                observation_recorder=self.observation_recorder,
            )

            self._is_running = True
            logger.info(
                f"[{self.session_id}] [LangGraph] State graph started — _is_running={self._is_running}"
            )

        except Exception as e:
            logger.error(f"[{self.session_id}] [LangGraph] Start failed: {e}")
            raise

    async def _load_tools(self) -> None:
        """Load tools"""
        if self.tool_manager is not None:
            if not self.tool_manager.is_loaded():
                raise RuntimeError("prebuilt tool manager is not loaded")
            self._langgraph_config["configurable"].update(self.tool_manager.get_config())
            logger.info(
                "[{}] [LangGraph] Reusing {} prebuilt tools",
                self.session_id,
                len(self.tool_manager.tools),
            )
            return

        self.tool_manager = ToolManager(self.session_id, self.service_context)
        success = await self.tool_manager.load_tools(self.tools_config)

        if success:
            # Update LangGraph config
            self._langgraph_config["configurable"].update(self.tool_manager.get_config())
            logger.info(f"[{self.session_id}] [LangGraph] Tool config added to LangGraph config")
        else:
            self.enable_tools = False
            logger.warning(
                f"[{self.session_id}] [LangGraph] Tool loading failed, tool calls disabled"
            )

    def _is_golden_profile(self) -> bool:
        system = getattr(getattr(self.service_context, "config", None), "system", None)
        return getattr(system, "runtime_profile", None) == "golden"

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
        message_id: str | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
        turn_id: str | None = None,
        tool_invocation_observer: ToolInvocationObserver | None = None,
        **metadata,
    ) -> dict[str, Any]:
        """Process text input.

        Central ingress defense: even if a transport handler forgets to call
        ``is_probe_message`` (the historical ``desktop.chat_message`` and
        Bilibili danmaku paths did not), a probe-shaped text — bare ``"ping"``,
        ``"[inspection] ..."`` etc. — is dropped here before the graph runs,
        so no caller can route an internal probe into the LLM. This mirrors the
        text-only branch of ``message_filter.should_skip_llm`` and is purely a
        backstop: real user text (including a danmaku that happens to say
        ``"用户名说: ping"``, which is not a bare probe token) still flows
        through unchanged.
        """
        if not self._is_running:
            return {"error": "Orchestrator not started"}

        if should_skip_llm(text):
            logger.debug(
                f"[{self.session_id}] [LangGraph] Dropping probe-shaped text before graph run"
            )
            return {
                "response_text": "",
                "response_chunks": [],
                "tts_audio": None,
                "emotion": None,
                "error": None,
                "message_id": message_id,
                "conversation_id": conversation_id,
                "task_id": task_id,
                "turn_id": turn_id,
            }

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
                message_id=message_id,
                conversation_id=conversation_id,
                task_id=task_id,
                turn_id=turn_id,
                metadata=metadata,
            )
            final_state = await self._run_graph(
                initial_state,
                tool_invocation_observer=tool_invocation_observer,
            )
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
        message_id: str | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
        turn_id: str | None = None,
        **metadata,
    ) -> dict[str, Any]:
        """Process audio input"""
        if not self._is_running:
            return {"error": "Orchestrator not started"}

        if self._processing_audio:
            logger.debug(f"[{self.session_id}] [LangGraph] Audio already processing, skipping")
            return {"error": "Audio already processing"}

        self._processing_audio = True
        logger.info(
            f"[{self.session_id}] [LangGraph] Processing audio input: {len(audio_data)} bytes"
        )

        get_interrupt_handler().clear_interrupt(self.session_id)

        try:
            initial_state = self._create_initial_state(
                input_type="audio",
                raw_audio=audio_data,
                channel_id=channel_id,
                user_id=user_id,
                user_name=user_name,
                message_id=message_id,
                conversation_id=conversation_id,
                task_id=task_id,
                turn_id=turn_id,
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
        message_id: str | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
        turn_id: str | None = None,
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
            message_id=message_id,
            conversation_id=conversation_id,
            task_id=task_id,
            turn_id=turn_id,
        )

        if metadata:
            initial_state["metadata"] = metadata

        config_version = int(getattr(self.service_context, "runtime_config_version", 1) or 1)
        config_hash = getattr(self.service_context, "runtime_config_hash", None)
        initial_state["config_version"] = config_version
        initial_state["metadata"] = {
            **initial_state.get("metadata", {}),
            "config_version": config_version,
            "config_hash": config_hash,
            "message_id": message_id,
            "conversation_id": conversation_id,
            "task_id": task_id,
            "turn_id": turn_id,
        }

        return initial_state

    async def _run_graph(
        self,
        initial_state: AgentState,
        *,
        tool_invocation_observer: ToolInvocationObserver | None = None,
    ) -> dict[str, Any]:
        """Run the state graph, passing service context through LangGraph config"""
        input_type = initial_state.get("input_type", "text")
        metadata = initial_state.get("metadata", {})
        scope = resolve_conversation_scope(
            conversation_id=initial_state.get("conversation_id"),
            session_id=self.session_id,
            metadata=metadata,
        )
        async with self.conversation_registry.turn(scope) as conversation_session:
            window_before = len(conversation_session.completed_turns)
            initial_state["metadata"] = {
                **metadata,
                "conversation_scope_kind": scope.kind,
                "conversation_window_pairs_before": window_before,
                "has_private_developer_context": (
                    conversation_session.has_private_developer_context
                ),
            }
            turn = await self._conversation_observer().start(initial_state)
            run_config = cast(
                RunnableConfig,
                {
                    **self._langgraph_config,
                    "configurable": dict(self._langgraph_config.get("configurable", {})),
                },
            )
            run_config["configurable"]["conversation_session"] = conversation_session
            checkpoint_thread_id = initial_state.get("metadata", {}).get("checkpoint_thread_id")
            if isinstance(checkpoint_thread_id, str) and checkpoint_thread_id:
                run_config["configurable"]["thread_id"] = checkpoint_thread_id
            from .tool_observation import (
                CompositeToolInvocationObserver,
                LedgerToolInvocationObserver,
            )

            ledger_tool_observer = LedgerToolInvocationObserver(
                self.observation_recorder,
                digest_salt=self._observation_digest_salt(),
            )
            if tool_invocation_observer is None:
                run_config["configurable"]["tool_invocation_observer"] = ledger_tool_observer
            else:
                run_config["configurable"]["tool_invocation_observer"] = tool_invocation_observer
                run_config["configurable"]["effective_tool_invocation_observer"] = (
                    CompositeToolInvocationObserver(tool_invocation_observer, ledger_tool_observer)
                )
            callbacks = self._callbacks or get_observability().callbacks
            if callbacks:
                run_config["callbacks"] = callbacks

            logger.info(
                "[{}] [LangGraph] _run_graph starting — input_type={}, scope_kind={}, "
                "window_pairs={}",
                self.session_id,
                input_type,
                scope.kind,
                window_before,
            )
            t_start = time_module.perf_counter()

            try:
                graph = self.graph
                if graph is None:
                    raise RuntimeError("State graph is not initialized")
                result = await graph.ainvoke(initial_state, config=run_config)
                duration_ms = (time_module.perf_counter() - t_start) * 1000
                logger.info(
                    "[{}] [LangGraph] _run_graph completed in {:.0f}ms — "
                    "scope_kind={}, window_pairs={}",
                    self.session_id,
                    duration_ms,
                    scope.kind,
                    len(conversation_session.completed_turns),
                )
                await turn.finish(result)
                return result
            except asyncio.CancelledError as exc:
                await turn.fail(exc)
                raise
            except Exception as e:
                duration_ms = (time_module.perf_counter() - t_start) * 1000
                logger.error(
                    f"[{self.session_id}] [LangGraph] _run_graph failed after {duration_ms:.0f}ms: {e}"
                )
                await turn.fail(e)
                raise

    def _conversation_observer(self) -> ConversationObserver:
        config = getattr(self.service_context, "config", None)
        system = getattr(config, "system", None)
        profile = str(getattr(system, "runtime_profile", "development") or "development")
        observation = getattr(config, "observability", None)
        privacy = getattr(observation, "privacy", None)
        salt = self._observation_digest_salt()
        privacy_name = str(
            getattr(privacy, profile, "")
            or getattr(
                privacy,
                "production" if profile in {"prod", "production"} else profile,
                "",
            )
        )
        privacy_mode = (
            PrivacyMode(privacy_name)
            if privacy_name in {mode.value for mode in PrivacyMode}
            else None
        )
        return ConversationObserver(
            self.observation_recorder,
            runtime_profile=profile,
            digest_salt=salt,
            privacy_mode=privacy_mode,
        )

    def _observation_digest_salt(self) -> str:
        config = getattr(self.service_context, "config", None)
        observation = getattr(config, "observability", None)
        privacy = getattr(observation, "privacy", None)
        return str(
            getattr(privacy, "digest_salt", "animetta-local-observation")
            or "animetta-local-observation"
        )

    def _clean_result(self, final_state: dict[str, Any]) -> dict[str, Any]:
        """Clean up return value"""
        return {
            "response_text": final_state.get("response_text", ""),
            "response_chunks": final_state.get("response_chunks", []),
            "tts_audio": final_state.get("tts_audio"),
            "emotion": final_state.get("emotion"),
            "error": final_state.get("error"),
            "message_id": final_state.get("message_id"),
            "conversation_id": final_state.get("conversation_id"),
            "task_id": final_state.get("task_id"),
            "turn_id": final_state.get("turn_id"),
            "memory_recall": final_state.get("memory_recall", {}),
        }

    def _get_system_prompt(self) -> str | None:
        """Get a compatibility fallback; per-turn prompt ownership is in the pipeline."""
        if self.service_context and self.service_context.config:
            return self.service_context.config.get_system_prompt()
        return None

    def _get_persona_dict(self) -> dict[str, Any] | None:
        """Get persona config dict"""
        if self.service_context and self.service_context.config:
            persona = self.service_context.config.get_persona()
            if persona:
                result = {
                    "name": persona.name,
                    "role": persona.role,
                    "identity": persona.identity,
                    "personality": persona.personality.dict()
                    if hasattr(persona.personality, "dict")
                    else {},
                    "behavior": persona.behavior.dict()
                    if hasattr(persona.behavior, "dict")
                    else {},
                    "speaking_style": persona.speaking_style,
                }
                # Include MBTI profile if configured
                if persona.personality.mbti:
                    result["mbti"] = (
                        persona.personality.mbti.dict()
                        if hasattr(persona.personality.mbti, "dict")
                        else {}
                    )
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
        observation_recorder: ObservationRecorder | None = None,
        tool_manager: ToolManager | None = None,
        conversation_registry: ConversationSessionRegistry | None = None,
    ) -> LangGraphOrchestrator:
        """Create orchestrator instance

        The returned orchestrator is owned by the caller (``SessionManager``
        stores it in its per-session ``orchestrators`` dict and is responsible
        for cleanup via ``orchestrator.stop()``).
        """
        orchestrator = LangGraphOrchestrator(
            service_context=service_context,
            socketio=socketio,
            emotion_analyzer=emotion_analyzer,
            enable_tools=enable_tools,
            enable_memory=enable_memory,
            tools_config=tools_config,
            observation_recorder=observation_recorder,
            tool_manager=tool_manager,
            conversation_registry=conversation_registry,
        )

        await orchestrator.start()
        return orchestrator
