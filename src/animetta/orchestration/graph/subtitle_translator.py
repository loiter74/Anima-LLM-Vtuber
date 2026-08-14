"""Stateless subtitle translation helper.

Translates response text for subtitle display without mutating the main
conversation history or reusing the Anima roleplay system prompt.

Design decisions (from design.md):
- Require chat_messages() with isolated messages; never use history-mutating chat().
- Strip runtime markers (emotion, affinity) before translation.
- Skip translation if a provider does not implement the explicit-messages contract.
"""

from __future__ import annotations

import re

from loguru import logger

from animetta.services.llm.interface import LLMInterface
from animetta.services.llm.internal_calls import has_native_chat_messages

# ── Marker patterns to strip before translation ──────────────────

# Emotion tags: [happy], [sad], [angry], [surprised], [thinking], [neutral]
_EMOTION_TAG_RE = re.compile(r"\[(happy|sad|angry|surprised|thinking|neutral)\]", re.IGNORECASE)

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

    Strip runtime markers, then use the provider's history-neutral messages API.
    Providers without that contract are skipped.
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

    if not has_native_chat_messages(llm):
        logger.warning(
            "[SubtitleTranslator] Cannot safely translate — provider lacks native "
            "chat_messages. Skipping subtitle translation."
        )
        return None

    try:
        translated = await llm.chat_messages(messages, temperature=0)
        if translated and translated.strip():
            return translated.strip()
        return None
    except Exception as e:
        logger.warning(f"[SubtitleTranslator] chat_messages() failed: {e}")
        return None
