"""Emotion analysis node"""

from typing import Any

from langgraph.types import RunnableConfig
from loguru import logger

from animetta.memory.v2.emotion_field import VAD_MAP

from .state import AgentState


def _get_from_config(config: RunnableConfig | None, key: str) -> Any | None:
    """Get value from LangGraph config"""
    if config:
        return config.get("configurable", {}).get(key)
    return None


def _emotion_result(emotion: str) -> dict[str, Any]:
    """Build result dict with both discrete emotion and VAD vector."""
    vad = VAD_MAP.get(emotion, VAD_MAP["neutral"])
    return {"emotion": emotion, "emotion_vad": vad.to_tuple()}


async def emotion_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """
    Emotion analysis node

    Input: state["response_text"]
    Output: state["emotion"]
    """
    session_id = state.get("session_id", "unknown")
    # Prefer response_chunks (raw text with [emotion] tags intact) over
    # response_text (tags already stripped by llm_node).
    response_chunks = state.get("response_chunks") or []
    response_text = response_chunks[0] if response_chunks else state.get("response_text", "")

    logger.info(f"[{session_id}] [EmotionNode] Starting analysis...")

    if not response_text:
        logger.warning(f"[{session_id}] [EmotionNode] No response text, using default emotion")
        return _emotion_result("neutral")

    # Get emotion_analyzer from config
    emotion_analyzer = _get_from_config(config, "emotion_analyzer")

    if not emotion_analyzer:
        # Try to get from service_context
        service_context = _get_from_config(config, "service_context")
        if service_context and hasattr(service_context, "emotion_analyzer"):
            emotion_analyzer = service_context.emotion_analyzer

    if not emotion_analyzer:
        logger.debug(f"[{session_id}] [EmotionNode] No emotion analyzer, using default emotion")
        return _emotion_result("neutral")

    try:
        logger.debug(f"[{session_id}] [EmotionNode] Calling emotion analyzer...")

        result = emotion_analyzer.extract(response_text)
        primary_emotion = result.primary
        confidence = result.confidence

        logger.info(f"[{session_id}] [EmotionNode] Analysis result: {primary_emotion} (confidence: {confidence:.2f})")

        return _emotion_result(primary_emotion)

    except Exception as e:
        logger.error(f"[{session_id}] [EmotionNode] Analysis failed: {e}")
        return _emotion_result("neutral")
