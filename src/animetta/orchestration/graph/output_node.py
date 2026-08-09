"""Output distribution node - Socket.IO push + memory storage"""

import asyncio
import base64
import os
from functools import partial
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from loguru import logger

from animetta.avatar.analyzers.audio import AudioAnalyzer, trim_leading_silence
from animetta.avatar.performance import validated_performance_payload
from animetta.observability.context import noncritical_observation_context
from animetta.orchestration.chat_contracts import ChatIdentity, ChatTransportMode
from animetta.orchestration.chat_delivery import ChatDelivery, resolve_delivery_target
from animetta.utils.tempfiles import write_temp_bytes

from .media_status import MediaStatus
from .persistence_policy import PersistenceMode, PersistenceRequest, decide_persistence
from .state import AgentState
from .subtitle_translator import translate_subtitle_text
from .translation_state import translation_state


def _get_from_config(config: RunnableConfig | None, key: str) -> Any | None:
    """Get value from LangGraph config"""
    if config:
        return config.get("configurable", {}).get(key)
    return None


def _is_golden_profile(config: RunnableConfig | None) -> bool:
    context = _get_from_config(config, "service_context")
    system = getattr(getattr(context, "config", None), "system", None)
    return getattr(system, "runtime_profile", None) == "golden"


def _public_tts_degradation_reason(reason: str | None) -> str:
    """Map provider-specific failures onto the declared public chat contract."""
    if reason == "timeout":
        return "timeout"
    if reason in {"busy", "rate_limit"}:
        return "rate_limit"
    if reason in {"empty_audio", "invalid_audio"}:
        return "empty_audio"
    if reason in {
        "connection",
        "not_ready",
        "provider_unavailable",
        "service_unavailable",
        "unavailable",
    }:
        return "unavailable"
    return "provider_error"


async def output_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """
    Output distribution node

    Push text and audio to frontend via Socket.IO, store conversation in memory system
    """
    session_id = state.get("session_id", "unknown")

    logger.info(f"[{session_id}] [OutputNode] Starting distribution...")

    sio = _get_from_config(config, "socketio")
    if not sio:
        logger.error(f"[{session_id}] [OutputNode] Socket.IO not configured")
        return {"error": "Socket.IO not configured"}

    to = resolve_delivery_target(state)
    identity = ChatIdentity(
        message_id=state["message_id"],
        conversation_id=state["conversation_id"],
        task_id=state["task_id"],
        turn_id=state["turn_id"],
    )
    metadata = state.get("metadata", {}) or {}
    transport_mode = ChatTransportMode(
        metadata.get("transport_mode", ChatTransportMode.CANONICAL.value)
    )
    recorder = _get_from_config(config, "observation_recorder")
    delivery = (
        ChatDelivery(sio, identity, transport_mode, recorder=recorder)
        if recorder is not None
        else ChatDelivery(sio, identity, transport_mode)
    )

    # Split-delivery graphs publish start/text before the blocking TTS node.
    # Legacy/direct callers still receive the complete event sequence here.
    if "conversation_started_at" not in metadata:
        await delivery.emit("chat", "control", {"signal": "conversation-start"}, to=to)

    # Store conversation in memory system
    if not _is_golden_profile(config):
        await _store_conversation_to_memory(state=state, config=config)

    # Send text response
    response_text = state.get("response_text", "")
    if response_text and "text_ready_at" not in metadata:
        # ── 1. Send original text immediately (no blocking) ──
        lang = translation_state.source_language.lower()[:2]
        sentence_payload = {
            "text": response_text,
            "seq": 0,
            "lang": lang,
        }
        await delivery.emit("chat", "sentence", sentence_payload, to=to)
        logger.info(f"[{session_id}] [OutputNode] ✅ Sent text response")

        await delivery.emit(
            "chat",
            "sentence",
            {"text": "", "seq": 1, "lang": lang, "is_complete": True},
            to=to,
        )
        logger.debug(f"[{session_id}] [OutputNode] ✅ Sent stream end marker")

    # Run translation concurrently after the canonical text has been delivered.
    # Golden turns have a hard two-call budget, so their legacy LLM translator
    # remains disabled.
    translation_task: asyncio.Task[None] | None = None
    translation_window_open = True
    if translation_state.enabled and response_text and not _is_golden_profile(config):

        async def _translate_and_emit():
            with noncritical_observation_context():
                try:
                    service_context = _get_from_config(config, "service_context")
                    if (
                        service_context
                        and hasattr(service_context, "llm_engine")
                        and service_context.llm_engine
                    ):
                        llm = service_context.llm_engine
                        translated = await translate_subtitle_text(
                            llm,
                            response_text,
                            source_lang=translation_state.source_language,
                            target_lang=translation_state.target_language,
                        )
                        if translated and translation_window_open:
                            target_lang = translation_state.target_language.lower()[:2]
                            await delivery.emit(
                                "chat",
                                "subtitle_translation",
                                {
                                    "translation": translated,
                                    "target_lang": target_lang,
                                },
                                to=to,
                            )
                            logger.info(
                                f"[{session_id}] [OutputNode] ✅ Translated response to {translation_state.target_language}"
                            )
                except Exception as e:
                    logger.warning(f"[{session_id}] [OutputNode] Translation failed: {e}")

        translation_task = asyncio.create_task(_translate_and_emit())

    # Keep the legacy expression event for compatibility. Semantic performance
    # is synchronized with actual audio below and never exposes motion indices.
    emotion = state.get("emotion")
    if emotion:
        await delivery.emit("chat", "expression", {"emotion": emotion}, to=to)
        logger.debug(f"[{session_id}] [OutputNode] Sent emotion: {emotion}")

    # Send audio data (with parallel processing for independent operations)
    tts_audio = state.get("tts_audio")
    if tts_audio:
        try:
            audio_data: str | None = None
            format = "wav"  # default to WAV for byte-returning TTS providers
            volumes: list[float] = []

            if isinstance(tts_audio, str) and os.path.exists(tts_audio):
                # ── Trim leading silence first, then parallel read + volumes ──
                loop = asyncio.get_running_loop()
                trimmed_path = await loop.run_in_executor(None, _trim_leading_silence, tts_audio)
                audio_source = trimmed_path or tts_audio

                (raw_bytes, vol_result) = await asyncio.gather(
                    loop.run_in_executor(None, partial(_read_file_bytes, audio_source)),
                    loop.run_in_executor(None, _compute_volumes, audio_source),
                )

                ext = os.path.splitext(audio_source)[1].lower()
                format = ext.lstrip(".") if ext else "wav"
                audio_data = base64.b64encode(raw_bytes).decode("utf-8")
                volumes = vol_result or []

            elif isinstance(tts_audio, bytes):
                # Detect audio format from magic bytes before encoding
                if tts_audio[:4] == b"RIFF":
                    format = "wav"
                elif tts_audio[:3] == b"ID3" or (
                    tts_audio[0] == 0xFF and (tts_audio[1] & 0xE0) == 0xE0
                ):
                    format = "mp3"
                elif tts_audio[:4] == b"OggS":
                    format = "ogg"
                audio_data = base64.b64encode(tts_audio).decode("utf-8")
                # Write bytes to a temp file so we can compute volume envelope for lip sync.
                tmp_audio = write_temp_bytes(tts_audio, suffix=f".{format}")
                volumes = _compute_volumes(tmp_audio)

            if audio_data:
                payload: dict[str, Any] = {"audio_data": audio_data, "format": format}
                if volumes:
                    payload["volumes"] = volumes
                performance = validated_performance_payload(state.get("performance_plan"))
                if performance is not None:
                    payload["performance"] = performance
                await delivery.emit("chat", "audio_with_expression", payload, to=to)
                logger.info(
                    f"[{session_id}] [OutputNode] ✅ Sent audio data (volumes: {len(volumes)} samples)"
                )

        except Exception as e:
            logger.error(f"[{session_id}] [OutputNode] Audio processing failed: {e}")
            await delivery.emit(
                "chat",
                "control",
                {
                    "type": "media-degraded",
                    "status": "degraded",
                    "component": "tts",
                    "phase": "media",
                    "reason": "provider_error",
                    "retryable": True,
                    "text": "Audio unavailable; continuing with text.",
                },
                to=to,
            )
    else:
        media_status = state.get("media_status")
        if isinstance(media_status, MediaStatus) and media_status.status == "degraded":
            await delivery.emit(
                "chat",
                "control",
                {
                    "type": "media-degraded",
                    "status": "degraded",
                    "component": "tts",
                    "phase": "media",
                    "reason": _public_tts_degradation_reason(media_status.reason),
                    "retryable": media_status.retryable,
                    "text": "Audio unavailable; continuing with text.",
                },
                to=to,
            )

    # conversation-end is terminal for this turn. Give the non-critical
    # translator a short grace window, then cancel it before publishing the
    # terminal frame so no late chat event can leak into the next turn.
    if translation_task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(translation_task), timeout=1.0)
        except TimeoutError:
            translation_window_open = False
            translation_task.cancel()
            try:
                await translation_task
            except asyncio.CancelledError:
                logger.debug(
                    f"[{session_id}] [OutputNode] Translation cancelled before terminal frame"
                )

    # Send conversation-end signal
    await delivery.emit("chat", "control", {"signal": "conversation-end"}, to=to)

    logger.info(f"[{session_id}] [OutputNode] Distribution complete")
    return {}


def _read_file_bytes(path: str) -> bytes:
    """Read a file as bytes (runs in thread pool)."""
    with open(path, "rb") as f:
        return f.read()


def _trim_leading_silence(audio_path: str) -> str | None:
    """Trim leading silence from audio and return path to trimmed file.

    This ensures audio playback and lip sync both start when speech begins.
    Returns None if no trimming was needed.
    """
    try:
        trimmed_path = trim_leading_silence(audio_path)
        if trimmed_path:
            logger.debug("[output_node] Trimmed leading silence from audio")
        return trimmed_path
    except Exception as e:
        logger.debug(f"[output_node] Silence trimming skipped: {e}")
        return None


def _compute_volumes(audio_path: str) -> list:
    """Compute the volume envelope of an audio file for lip sync.

    Uses peak amplitude WITHOUT global normalization, so a loud sound
    at the start doesn't suppress the rest of the mouth movement.
    """
    try:
        analyzer = AudioAnalyzer()
        volumes = analyzer.compute_volume_envelope(
            audio_path, normalize=False, gain=3.5, use_peak=True
        )

        # Clamp to [0, 1] after gain
        if volumes:
            volumes = [min(1.0, v) for v in volumes]
            non_zero = sum(1 for v in volumes if v > 0.01)
            logger.info(
                f"[output_node] Volumes: {len(volumes)} frames, "
                f"{non_zero} non-zero, "
                f"range=[{min(volumes):.3f}, {max(volumes):.3f}], "
                f"first_10={[round(v, 2) for v in volumes[:10]]}"
            )

        return volumes
    except Exception as e:
        logger.debug(f"[output_node] Computing volumes failed: {e}")
        return []


async def _store_conversation_to_memory(
    state: AgentState,
    config: RunnableConfig | None,
) -> None:
    """Store conversation turn into LivingMemorySystem V2."""
    session_id = state.get("session_id", "unknown")

    try:
        service_context = _get_from_config(config, "service_context")
        if not service_context:
            return

        memory_system = getattr(service_context, "memory_system", None)
        if not memory_system:
            return

        user_text = state.get("user_text", "")
        response_text = state.get("response_text", "")

        if not user_text or not response_text:
            return

        system = getattr(getattr(service_context, "config", None), "system", None)
        configured_mode = getattr(system, "long_term_memory_mode", "off")
        mode = (
            cast(PersistenceMode, configured_mode)
            if configured_mode in {"off", "read_only", "read_write"}
            else "off"
        )
        status = state.get("metadata", {}).get("dialogue_status")
        decision = decide_persistence(
            PersistenceRequest(
                mode=mode,
                sink="long_term_write",
                content_class=(
                    "selected_final"
                    if status in {"composer", "composer_fallback"}
                    else "incomplete"
                ),
                completed=status in {"composer", "composer_fallback"},
                real_provider=status in {"composer", "composer_fallback"},
            )
        )
        if not decision.allowed:
            logger.debug(f"[{session_id}] [OutputNode] Memory write rejected: {decision.reason}")
            return

        # ── Don't pollute context with non-Anima replies ──
        # Fallback responses (LLM timeout, MockLLM templates, customer-service
        # flavor) must never enter V2 memory, or the next turn will treat them
        # as something Anima actually said — the "角色污染" half of the bug.
        if _is_unpersistable_response(state, response_text):
            logger.info(
                f"[{session_id}] [OutputNode] Skipping memory storage "
                f"for fallback/template reply (len={len(response_text)})"
            )
            return

        vad_tuple = state.get("response_emotion_vad") or state.get("emotion_vad")
        from animetta.core.shared_memory_runtime import ConversationTurn
        from animetta.memory.v2.context import MemoryContext, normalize_actor_id
        from animetta.memory.v2.emotion_field import VADVector

        vad = VADVector(*vad_tuple) if vad_tuple else None

        metadata = state.get("metadata", {}) or {}
        channel = metadata.get("channel") or "unknown"
        context = MemoryContext(
            actor_id=normalize_actor_id(
                state.get("user_id") or metadata.get("actor_id"),
                channel,
            ),
            conversation_id=state.get("conversation_id") or metadata.get("conversation_id"),
            stream_id=metadata.get("stream_id"),
            persona_id=metadata.get("persona_id"),
            channel=channel,
            connection_id=session_id,
            actor_role=metadata.get("actor_role"),
            source=metadata.get("source"),
            live_session_id=metadata.get("live_session_id"),
            message_id=state.get("message_id") or metadata.get("message_id"),
            task_id=state.get("task_id") or metadata.get("task_id"),
            turn_id=state.get("turn_id") or metadata.get("turn_id"),
            audience=metadata.get("audience"),
        )

        # Production sessions borrow the application-scoped runtime. Database
        # and embedding work runs on its bounded ingestion worker after output.
        memory_runtime = vars(service_context).get("memory_runtime")
        if memory_runtime is not None:
            from animetta.observability.context import (
                ObservationCarrier,
                get_observation_context,
            )

            active_observation = get_observation_context()
            carrier = (
                ObservationCarrier.from_context(active_observation)
                if active_observation is not None
                else None
            )
            accepted = memory_runtime.submit_turn(
                ConversationTurn(
                    user_input=user_text,
                    agent_response=response_text,
                    emotion_vad=vad,
                    context=context,
                    turn_id=state.get("turn_id") or metadata.get("turn_id"),
                    retention_policy=metadata.get("retention_policy", "standard"),
                    observation_carrier=carrier,
                )
            )
            logger.debug(f"[{session_id}] [OutputNode] Memory submission accepted={accepted}")
            return

        await memory_system.encode(
            user_input=user_text,
            agent_response=response_text,
            emotion_vad=vad,
            session_id=session_id,
            context=context,
        )

        logger.debug(f"[{session_id}] [OutputNode] Stored conversation in LivingMemory V2")

    except Exception as e:
        logger.warning(f"[{session_id}] [OutputNode] Memory storage failed: {e}")


# Markers that identify a reply as a non-Anima fallback / template.
# Such replies must not be persisted to V2 memory (would pollute persona).
# Kept short and unambiguous so genuine Anima lines never match.
_UNPERSISTABLE_MARKERS: tuple[str, ...] = (
    "I need a moment to think about that.",  # llm_node FALLBACK_RESPONSE (timeout)
    "有什么我可以帮助你的吗？",  # MockLLM customer-service template
    "我是一个 Mock LLM，用于测试和开发。",  # MockLLM self-identifying template
)


def _is_unpersistable_response(state: AgentState, response_text: str) -> bool:
    """Return True when ``response_text`` is a fallback/template that must not be persisted.

    Triggers on:
    - Any substring in ``_UNPERSISTABLE_MARKERS`` (timeout fallback, MockLLM templates).
    - The ``metadata["error_type"] == "timeout"`` flag set by ``llm_node`` on timeout.
    """
    for marker in _UNPERSISTABLE_MARKERS:
        if marker in response_text:
            return True

    metadata = state.get("metadata", {}) or {}
    return metadata.get("error_type") == "timeout"
