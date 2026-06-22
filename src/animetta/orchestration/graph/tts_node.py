"""TTS node - text to speech"""

import asyncio
import re
from typing import Any

from langgraph.types import RunnableConfig
from loguru import logger

from .node_error import log_node_error
from .state import AgentState

# Regex: emotion tags like [happy], [sad], [angry] etc.
_EMOTION_TAG_RE = re.compile(r'\[[\w-]+\]')

# Regex: Unicode Emoji ranges (only safe ranges that don't overlap with CJK)
_EMOJI_RE = re.compile(
    '[\U0001F600-\U0001F64F'   # Emoticons
    '\U0001F300-\U0001F5FF'   # Misc symbols & pictographs
    '\U0001F680-\U0001F6FF'   # Transport & map
    '\U0001F1E0-\U0001F1FF'   # Flags (regional indicators)
    '\U00002702-\U000027B0'   # Dingbats
    '\U0001F900-\U0001F9FF'   # Supplemental symbols
    '\U0001FA00-\U0001FA6F'   # Chess symbols
    '\U0001FA70-\U0001FAFF'   # Symbols extended-A
    '\U00002600-\U000026FF'   # Misc symbols
    '\U0000FE00-\U0000FE0F'   # Variation selectors
    '\U0000200D'              # Zero-width joiner
    ']'
)


def _clean_text_for_tts(text: str) -> str:
    """Remove emoji and emotion tags from text before TTS synthesis."""
    text = _EMOTION_TAG_RE.sub('', text)
    text = _EMOJI_RE.sub('', text)
    # Collapse multiple spaces into one
    text = re.sub(r'  +', ' ', text).strip()
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
        return {"tts_audio": None}

    service_context = _get_service_context(config)
    if not service_context:
        logger.error(f"[{session_id}] [TTSNode] service_context not configured")
        return {"error": "service_context not configured", "tts_audio": None}

    tts_engine = service_context.tts_engine
    if not tts_engine:
        logger.warning(f"[{session_id}] [TTSNode] TTS engine not initialized, skipping")
        return {"tts_audio": None}

    # Strip emoji and emotion tags before TTS so the voice doesn't read them aloud
    clean_text = _clean_text_for_tts(response_text)
    logger.debug(f"[{session_id}] [TTSNode] Text length: {len(response_text)} chars → {len(clean_text)} chars (cleaned)")

    try:
        # Darwin-TTS on CPU needs 2-5min per sentence, so use 300s timeout
        audio = await asyncio.wait_for(
            tts_engine.synthesize(clean_text), timeout=300.0
        )
    except TimeoutError:
        logger.warning(
            f"[{session_id}] [TTSNode] TTS timed out after 300s"
        )
        await log_node_error(session_id, "tts_node", "timeout", duration_ms=300000)
        return {"tts_audio": b"", "error": "TTS timed out after 300s"}
    except Exception as e:
        logger.warning(f"[{session_id}] [TTSNode] TTS failed ({type(e).__name__}): {e}")
        await log_node_error(session_id, "tts_node", "network_error", duration_ms=0)
        return {"tts_audio": b"", "error": str(e)}

    if isinstance(audio, bytes):
        logger.info(f"[{session_id}] [TTSNode] Audio data: {len(audio)} bytes")
    elif isinstance(audio, str):
        logger.info(f"[{session_id}] [TTSNode] Audio file: {audio}")

    return {"tts_audio": audio}
