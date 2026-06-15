"""ASR node - speech to text"""

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import RunnableConfig
from loguru import logger

from animetta.orchestration.socket_events import EVENTS

from .node_error import log_node_error
from .state import AgentState


def _get_service_context(config: RunnableConfig | None) -> Any | None:
    """Get service_context from LangGraph config"""
    if config:
        return config.get("configurable", {}).get("service_context")
    return None


async def asr_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """
    ASR speech recognition node

    Input: state["raw_audio"] (bytes)
    Output: state["user_text"] (str), state["messages"]
    """
    session_id = state.get("session_id", "unknown")
    raw_audio = state.get("raw_audio")

    logger.info(f"[{session_id}] [ASRNode] Starting audio processing...")

    if not raw_audio:
        logger.warning(f"[{session_id}] [ASRNode] No audio data, skipping")
        return {"error": "No audio data", "user_text": ""}

    service_context = _get_service_context(config)
    if not service_context:
        logger.error(f"[{session_id}] [ASRNode] service_context not configured")
        return {"error": "service_context not configured", "user_text": ""}

    asr_engine = service_context.asr_engine
    if not asr_engine:
        logger.error(f"[{session_id}] [ASRNode] ASR engine not initialized")
        return {"error": "ASR engine not initialized", "user_text": ""}

    try:
        text = await asr_engine.transcribe(raw_audio)
    except Exception as e:
        logger.warning(f"[{session_id}] [ASRNode] ASR failed ({type(e).__name__}): {e}")
        await log_node_error(session_id, "asr_node", "network_error", duration_ms=0)
        return {"error": str(e), "user_text": ""}
    logger.info(f"[{session_id}] [ASRNode] Recognition result: {text[:50]}...")

    # Emit transcript immediately so frontend shows user speech before LLM responds
    if text:
        try:
            sio = config.get("configurable", {}).get("socketio") if config else None
            if sio:
                await sio.emit(EVENTS["chat"]["transcript"]["name"], {"text": text, "is_final": True}, to=session_id)
        except Exception:
            logger.debug(f"[{session_id}] [ASRNode] Failed to emit transcript")

    user_id = state.get("user_id")
    user_name = state.get("user_name")

    content = f"[{user_name}]: {text}" if user_name else text
    message = HumanMessage(content=content, name=user_id or "user")

    return {"user_text": text, "messages": [message]}
