"""Golden-path split text and performance delivery nodes."""

import base64
import os
import time
from typing import Any

from langchain_core.runnables import RunnableConfig

from animetta.avatar.performance import validated_performance_payload
from animetta.orchestration.chat_contracts import ChatIdentity, ChatTransportMode
from animetta.orchestration.chat_delivery import ChatDelivery, resolve_delivery_target

from .media_status import MediaStatus
from .output_node import _compute_volumes, _public_tts_degradation_reason
from .state import AgentState, log_timing
from .translation_state import translation_state


def _delivery(
    state: AgentState,
    config: RunnableConfig | None,
) -> tuple[ChatDelivery | None, str | None]:
    configurable = config.get("configurable", {}) if config else {}
    sio = configurable.get("socketio")
    if sio is None:
        return None, ""
    identity = ChatIdentity(
        message_id=state["message_id"],
        conversation_id=state["conversation_id"],
        task_id=state["task_id"],
        turn_id=state["turn_id"],
    )
    mode = ChatTransportMode(
        state.get("metadata", {}).get("transport_mode", ChatTransportMode.CANONICAL.value)
    )
    recorder = configurable.get("observation_recorder")
    delivery = (
        ChatDelivery(sio, identity, mode, recorder=recorder)
        if recorder is not None
        else ChatDelivery(sio, identity, mode)
    )
    return delivery, resolve_delivery_target(state)


async def conversation_start_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    delivery, to = _delivery(state, config)
    if delivery is None:
        return {"error": "Socket.IO not configured"}
    await delivery.emit("chat", "control", {"signal": "conversation-start"}, to=to)
    return {"metadata": {**state.get("metadata", {}), "conversation_started_at": time.time()}}


async def reply_output_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    delivery, to = _delivery(state, config)
    if delivery is None:
        return {"error": "Socket.IO not configured"}
    response = state.get("response_text", "")
    if not response:
        return {"error": "No authored response"}
    lang = translation_state.source_language.lower()[:2]
    await delivery.emit("chat", "sentence", {"text": response, "seq": 0, "lang": lang}, to=to)
    await delivery.emit(
        "chat",
        "sentence",
        {"text": "", "seq": 1, "lang": lang, "is_complete": True},
        to=to,
    )
    started_at = float(state.get("metadata", {}).get("conversation_started_at", time.time()))
    log_timing(state, "text_ready", max(0.0, (time.time() - started_at) * 1000))
    return {"metadata": {**state.get("metadata", {}), "text_ready_at": time.time()}}


async def performance_output_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    delivery, to = _delivery(state, config)
    if delivery is None:
        return {"error": "Socket.IO not configured"}
    emotion = state.get("emotion") or "neutral"
    await delivery.emit("chat", "expression", {"emotion": emotion}, to=to)

    media = state.get("media_status")
    if not isinstance(media, MediaStatus):
        media = MediaStatus("ready" if state.get("tts_audio") else "skipped")
    audio = state.get("tts_audio")
    if media.status == "ready" and audio:
        raw, fmt = _audio_bytes(audio)
        if raw:
            volumes = _volumes(raw, fmt)
            payload: dict[str, Any] = {
                "audio_data": base64.b64encode(raw).decode("ascii"),
                "format": fmt,
                "volumes": volumes,
            }
            performance = validated_performance_payload(state.get("performance_plan"))
            if performance is not None:
                payload["performance"] = performance
            await delivery.emit("chat", "audio_with_expression", payload, to=to)
    elif media.status == "degraded":
        await delivery.emit(
            "chat",
            "control",
            {
                "type": "media-degraded",
                "status": "degraded",
                "component": "tts",
                "phase": "media",
                "reason": _public_tts_degradation_reason(media.reason),
                "retryable": media.retryable,
                "text": "Audio unavailable; continuing with text.",
            },
            to=to,
        )

    await delivery.emit("chat", "control", {"signal": "conversation-end"}, to=to)
    text_ready_at = float(state.get("metadata", {}).get("text_ready_at", time.time()))
    log_timing(state, "media_ready", max(0.0, (time.time() - text_ready_at) * 1000))
    return {"metadata": {**state.get("metadata", {}), "media_ready_at": time.time()}}


def _audio_bytes(audio: bytes | str) -> tuple[bytes, str]:
    if isinstance(audio, bytes):
        fmt = "wav" if audio[:4] == b"RIFF" else "mp3" if audio[:3] == b"ID3" else "wav"
        return audio, fmt
    if os.path.isfile(audio):
        with open(audio, "rb") as handle:
            return handle.read(), os.path.splitext(audio)[1].lstrip(".") or "wav"
    return b"", "wav"


def _volumes(raw: bytes, fmt: str) -> list[float]:
    from animetta.utils.tempfiles import write_temp_bytes

    return _compute_volumes(write_temp_bytes(raw, suffix=f".{fmt}"))
