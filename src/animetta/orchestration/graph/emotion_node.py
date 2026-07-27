"""Emotion analysis node"""

import time
from typing import Any

from langchain_core.runnables import RunnableConfig
from loguru import logger

from animetta.avatar.performance import PerformanceParseResult, parse_performance_plan
from animetta.memory.v2.emotion_field import VAD_MAP

from .state import AgentState, log_timing


def _emotion_result(
    state: AgentState,
    parsed: PerformanceParseResult,
) -> dict[str, Any]:
    """Build result dict with both discrete emotion and VAD vector."""
    emotion = parsed.compatible_emotion
    vad = VAD_MAP.get(emotion, VAD_MAP["neutral"])
    values = vad.to_tuple()
    metadata = {
        **(state.get("metadata", {}) or {}),
        "live2d_performance": {
            "source": parsed.plan.source,
            "base": parsed.plan.base,
            "accent": parsed.plan.accent,
            "fallback": parsed.fallback_reason or "none",
        },
    }
    return {
        "performance_plan": parsed.plan.to_dict(),
        "emotion": emotion,
        "emotion_vad": values,
        "response_emotion": emotion,
        "response_emotion_vad": values,
        "metadata": metadata,
    }


def _timed_result(
    state: AgentState,
    started: float,
    parsed: PerformanceParseResult,
) -> dict[str, Any]:
    log_timing(state, "emotion.analyze", (time.perf_counter() - started) * 1000)
    return _emotion_result(state, parsed)


async def emotion_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Normalize bounded Live2D performance and compatible emotion fields."""
    del config
    session_id = state.get("session_id", "unknown")
    started = time.perf_counter()
    response_chunks = state.get("response_chunks") or []
    response_text = "".join(response_chunks) if response_chunks else state.get("response_text", "")

    parsed = parse_performance_plan(response_text)
    logger.info(
        "[{}] [EmotionNode] Performance normalized: source={}, base={}, accent={}, fallback={}",
        session_id,
        parsed.plan.source,
        parsed.plan.base,
        parsed.plan.accent,
        parsed.fallback_reason or "none",
    )
    return _timed_result(state, started, parsed)
