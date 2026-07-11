"""TTS node - text to speech"""

import asyncio
import re
import time
from typing import Any

from langchain_core.runnables import RunnableConfig
from loguru import logger

from .media_status import MediaStatus
from .node_error import log_node_error
from .state import AgentState, log_timing

# Regex: emotion tags like [happy], [sad], [angry] etc.
_EMOTION_TAG_RE = re.compile(r"\[[\w-]+\]")

# Regex: Unicode Emoji ranges (only safe ranges that don't overlap with CJK)
_EMOJI_RE = re.compile(
    "[\U0001f600-\U0001f64f"  # Emoticons
    "\U0001f300-\U0001f5ff"  # Misc symbols & pictographs
    "\U0001f680-\U0001f6ff"  # Transport & map
    "\U0001f1e0-\U0001f1ff"  # Flags (regional indicators)
    "\U00002702-\U000027b0"  # Dingbats
    "\U0001f900-\U0001f9ff"  # Supplemental symbols
    "\U0001fa00-\U0001fa6f"  # Chess symbols
    "\U0001fa70-\U0001faff"  # Symbols extended-A
    "\U00002600-\U000026ff"  # Misc symbols
    "\U0000fe00-\U0000fe0f"  # Variation selectors
    "\U0000200d"  # Zero-width joiner
    "]"
)


def _clean_text_for_tts(text: str) -> str:
    """Remove emoji and emotion tags from text before TTS synthesis."""
    text = _EMOTION_TAG_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    # Collapse multiple spaces into one
    text = re.sub(r"  +", " ", text).strip()
    return text


def _get_service_context(config: RunnableConfig | None) -> Any | None:
    """Get service_context from LangGraph config"""
    if config:
        return config.get("configurable", {}).get("service_context")
    return None


async def tts_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """
    TTS speech synthesis node

    Input: state["response_text"]
    Output: state["tts_audio"] (bytes or str)
    """
    session_id = state.get("session_id", "unknown")
    response_text = state.get("response_text", "")

    logger.info(f"[{session_id}] [TTSNode] Starting processing...")

    if not response_text:
        logger.warning(f"[{session_id}] [TTSNode] No response text, skipping")
        return {"tts_audio": None, "media_status": MediaStatus("skipped", "no_text")}

    service_context = _get_service_context(config)
    if not service_context:
        logger.error(f"[{session_id}] [TTSNode] service_context not configured")
        return {
            "error": "service_context not configured",
            "tts_audio": None,
            "media_status": MediaStatus("degraded", "service_unavailable", retryable=True),
        }

    tts_engine = service_context.tts_engine
    if not tts_engine:
        logger.warning(f"[{session_id}] [TTSNode] TTS engine not initialized, skipping")
        return {
            "tts_audio": None,
            "media_status": MediaStatus("degraded", "provider_unavailable", retryable=True),
        }

    system = getattr(getattr(service_context, "config", None), "system", None)
    golden = getattr(system, "runtime_profile", None) == "golden"
    provider = type(tts_engine).__name__
    if golden and provider.lower() == "mocktts":
        return {
            "tts_audio": None,
            "media_status": MediaStatus("degraded", "mock_forbidden", provider, False),
        }

    # Strip emoji and emotion tags before TTS so the voice doesn't read them aloud
    clean_text = _clean_text_for_tts(response_text)
    logger.debug(
        f"[{session_id}] [TTSNode] Text length: {len(response_text)} chars → {len(clean_text)} chars (cleaned)"
    )

    try:
        started = time.perf_counter()
        timeout_seconds = (
            float(getattr(system, "golden_tts_timeout_seconds", 20.0)) if golden else 300.0
        )
        audio = await asyncio.wait_for(tts_engine.synthesize(clean_text), timeout=timeout_seconds)
    except TimeoutError:
        log_timing(
            state, "tts.synthesize", (time.perf_counter() - started) * 1000, "degraded:timeout"
        )
        logger.warning(f"[{session_id}] [TTSNode] TTS timed out")
        await log_node_error(session_id, "tts_node", "timeout", duration_ms=0)
        return {
            "tts_audio": None,
            "media_status": MediaStatus("degraded", "timeout", provider, True),
            "metadata": {
                **state.get("metadata", {}),
                "tts_provider": provider,
                "media_status": "degraded",
                "degradation_reason": "timeout",
            },
        }
    except Exception as e:
        log_timing(
            state,
            "tts.synthesize",
            (time.perf_counter() - started) * 1000,
            "degraded:provider_error",
        )
        logger.warning(f"[{session_id}] [TTSNode] TTS failed ({type(e).__name__}): {e}")
        await log_node_error(session_id, "tts_node", "network_error", duration_ms=0)
        return {
            "tts_audio": None,
            "media_status": MediaStatus("degraded", "provider_error", provider, True),
            "metadata": {
                **state.get("metadata", {}),
                "tts_provider": provider,
                "media_status": "degraded",
                "degradation_reason": "provider_error",
            },
        }

    if not audio or not isinstance(audio, (bytes, str)):
        log_timing(
            state, "tts.synthesize", (time.perf_counter() - started) * 1000, "degraded:empty_audio"
        )
        return {
            "tts_audio": None,
            "media_status": MediaStatus("degraded", "empty_audio", provider, True),
            "metadata": {
                **state.get("metadata", {}),
                "tts_provider": provider,
                "media_status": "degraded",
                "degradation_reason": "empty_audio",
            },
        }

    if isinstance(audio, bytes):
        logger.info(f"[{session_id}] [TTSNode] Audio data: {len(audio)} bytes")
    elif isinstance(audio, str):
        logger.info(f"[{session_id}] [TTSNode] Audio file: {audio}")

    log_timing(state, "tts.synthesize", (time.perf_counter() - started) * 1000, "ready")
    return {
        "tts_audio": audio,
        "media_status": MediaStatus("ready", provider=provider),
        "metadata": {
            **state.get("metadata", {}),
            "tts_provider": provider,
            "media_status": "ready",
        },
    }
