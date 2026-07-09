"""Stateless subtitle translation helper.

Translates response text for subtitle display without mutating the main
conversation history or reusing the Anima roleplay system prompt.

Design decisions (from design.md):
- Prefer chat_messages() with isolated messages over history-mutating chat().
- Strip runtime markers (emotion, affinity) before translation.
- Fall back safely: restore history or skip if safety cannot be guaranteed.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

from animetta.services.llm.interface import LLMInterface

if TYPE_CHECKING:
    pass  # LLMInterface imported above for runtime identity check

# ── Marker patterns to strip before translation ──────────────────

# Emotion tags: [happy], [sad], [angry], [surprised], [thinking], [neutral]
_EMOTION_TAG_RE = re.compile(
    r"\[(happy|sad|angry|surprised|thinking|neutral)\]", re.IGNORECASE
)

# Affinity markers: [affinity:75], [affinity: 50]
_AFFINITY_MARKER_RE = re.compile(r"\[affinity\s*:\s*\d+\]", re.IGNORECASE)

# Generic runtime bracket markers (catches future additions)
_RUNTIME_MARKER_RE = re.compile(r"\[[\w_]+:\s*\d+\]")

_SUBTITLE_SYSTEM_PROMPT = (
    "You are a subtitle translator for a VTuber character named Anima. "
    "Translate the user's text faithfully while preserving the character's "
    "tone — fatigue, light sarcasm, casual cyber-tavern phrasing. "
    "Translate from {source_lang} to {target_lang}. The target language is "
    "{target_lang}; do not output any other language unless it is a name, "
    "brand, or untranslatable term. "
    "Do NOT add new meaning, jokes, apologies, explanations, or answer the "
    "viewer. Output ONLY the translation in the target language, nothing else."
)


def _unwrap_service_proxy(service: object) -> object:
    """Return the wrapped service object when a tracing proxy is supplied."""
    try:
        return object.__getattribute__(service, "_target")
    except AttributeError:
        return service


def strip_runtime_markers(text: str) -> str:
    """Remove emotion tags, affinity markers, and other runtime-only markers.

    These markers are meaningful to the backend pipeline but should not
    appear in translated subtitles or confuse the translation LLM.
    """
    cleaned = _EMOTION_TAG_RE.sub("", text)
    cleaned = _AFFINITY_MARKER_RE.sub("", cleaned)
    cleaned = _RUNTIME_MARKER_RE.sub("", cleaned)
    # Collapse whitespace left behind by removed markers
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


async def translate_subtitle_text(
    llm: LLMInterface,
    source_text: str,
    source_lang: str = "Chinese",
    target_lang: str = "English",
) -> str | None:
    """Translate subtitle text using an isolated, history-safe call.

    Strategy:
    1. Strip runtime markers from source text.
    2. Try chat_messages() with an isolated message pair (no history access).
    3. If chat_messages() falls back to chat() (default impl), check whether
       the provider exposes get_history/set_system_prompt for restoration.
       - If yes: snapshot history, translate, restore.
       - If no: skip translation and log a warning.
    4. Return the translation string, or None if translation was skipped/failed.
    """
    cleaned = strip_runtime_markers(source_text)
    if not cleaned:
        return None

    system_prompt = _SUBTITLE_SYSTEM_PROMPT.format(
        source_lang=source_lang,
        target_lang=target_lang,
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Source subtitle ({source_lang}):\n{cleaned}"},
    ]

    # ── Detect whether chat_messages() is a native implementation ──
    # The base LLMInterface.chat_messages() default serializes to string
    # and calls chat(), which mutates history. We detect this by checking
    # if the method is overridden in the concrete class's MRO.
    llm_target = _unwrap_service_proxy(llm)
    has_native_chat_messages = (
        hasattr(type(llm_target), "chat_messages")
        and type(llm_target).chat_messages is not LLMInterface.chat_messages
    )

    if has_native_chat_messages:
        # Safe path: isolated call, no history mutation
        try:
            translated = await llm.chat_messages(messages, temperature=0)
            if translated and translated.strip():
                return translated.strip()
            return None
        except Exception as e:
            logger.warning(f"[SubtitleTranslator] chat_messages() failed: {e}")
            return None

    # ── Fallback: chat_messages() delegates to chat() (history-mutating) ──
    # We need to snapshot and restore history to prevent translation prompts
    # from polluting subsequent main chat turns.
    logger.debug(
        "[SubtitleTranslator] chat_messages() not natively implemented, "
        "using history-snapshot fallback"
    )

    can_restore = False
    try:
        # Check that get_history actually returns something usable
        test_history = llm_target.get_history()
        can_restore = isinstance(test_history, list) and hasattr(llm_target, "clear_history")
    except Exception:
        can_restore = False

    if not can_restore:
        logger.warning(
            "[SubtitleTranslator] Cannot safely translate — LLM lacks "
            "get_history/set_system_prompt. Skipping subtitle translation."
        )
        return None

    # Snapshot current state
    saved_history = llm_target.get_history()
    try:
        translated = await llm.chat_messages(messages, temperature=0)
        if translated and translated.strip():
            return translated.strip()
        return None
    except Exception as e:
        logger.warning(f"[SubtitleTranslator] Fallback translation failed: {e}")
        return None
    finally:
        # Always restore history, even on failure
        try:
            llm_target.clear_history()
            for msg in saved_history:
                # Re-populate history by re-adding messages
                if hasattr(llm_target, '_history'):
                    llm_target._history.append(msg)
                elif hasattr(llm_target, 'history'):
                    llm_target.history.append(msg)
            logger.debug("[SubtitleTranslator] History restored after fallback translation")
        except Exception as restore_err:
            logger.error(
                f"[SubtitleTranslator] Failed to restore history: {restore_err}. "
                "Translation may have leaked into main conversation."
            )
