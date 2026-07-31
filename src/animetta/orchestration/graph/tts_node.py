"""TTS node - text to speech"""

import asyncio
import base64
import re
import time
from contextlib import suppress
from typing import Any
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from loguru import logger

from animetta.avatar.performance import parse_performance_plan, validated_performance_payload
from animetta.core.readiness import resolve_service_identity, unwrap_tracing_proxy
from animetta.orchestration.chat_contracts import ChatIdentity, ChatTransportMode
from animetta.orchestration.chat_delivery import ChatDelivery
from animetta.services.tts.emotion_instructions import build_emotion_instruction
from animetta.services.tts.remote_tts import RemoteTTSError

from .interrupt_handler import get_interrupt_handler
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
_INTERRUPT_CLEANUP_GRACE_SECONDS = 0.2
_RETRYABLE_REMOTE_STREAM_DELAYS_SECONDS = (0.25, 0.75, 1.5, 3.0)


def _clean_text_for_tts(text: str) -> str:
    """Remove emoji and emotion tags from text before TTS synthesis."""
    text = parse_performance_plan(text).cleaned_text
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


def _resolve_provider_identity(
    service_context: Any,
    tts_engine: Any,
) -> tuple[str, str | None, bool]:
    """Return bounded actual provider metadata and config-match status."""
    runtime_config = getattr(service_context, "config", None)
    providers = getattr(runtime_config, "providers", None)
    configured = providers.get("tts") if hasattr(providers, "get") else None
    if configured is not None:
        identity = resolve_service_identity("tts", tts_engine, configured)
        if identity is None:
            return "unknown", None, False
        expected = configured.public_identity()
        matches = all(
            identity.get(field) == expected.get(field)
            for field in ("type", "provider", "model", "voice")
            if expected.get(field) is not None
        )
        provider = identity.get("provider") or identity.get("type") or "unknown"
        return provider, identity.get("type"), matches

    target = unwrap_tracing_proxy(tts_engine)
    if target is None:
        return "unknown", None, False
    class_name = type(target).__name__
    return class_name, None, True


def _stream_delivery(
    state: AgentState,
    config: RunnableConfig | None,
) -> tuple[ChatDelivery | None, str]:
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
    return delivery, state.get("channel_id") or state["session_id"]


async def _emit_stream_end(
    delivery: ChatDelivery,
    *,
    to: str,
    stream_id: str,
    final_sequence: int,
    status: str,
    reason: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "stream_id": stream_id,
        "final_sequence": final_sequence,
        "status": status,
    }
    if reason is not None:
        payload["reason"] = reason
    await delivery.emit("chat", "audio_stream_end", payload, to=to)


class _UserInterruptedError(Exception):
    """Internal control flow for a prompt user interruption."""


def _consume_background_task(task: asyncio.Task[Any]) -> None:
    """Consume a detached cleanup result so it cannot warn at shutdown."""
    with suppress(BaseException):
        task.result()


async def _settle_cancelled_task(task: asyncio.Task[Any]) -> None:
    """Cancel provider I/O without allowing cleanup to hold the turn lock."""
    if task.done():
        _consume_background_task(task)
        return
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=_INTERRUPT_CLEANUP_GRACE_SECONDS)
    if task in done:
        _consume_background_task(task)
    else:
        task.add_done_callback(_consume_background_task)


async def _close_async_stream(
    stream: Any | None,
    *,
    timeout_seconds: float | None = None,
) -> None:
    """Finalize a provider iterator before retrying or returning."""
    if stream is None:
        return
    close = getattr(stream, "aclose", None)
    if close is None:
        return

    async def _run_close() -> None:
        await close()

    if timeout_seconds is None:
        try:
            await _run_close()
        except (Exception, asyncio.CancelledError):
            logger.debug("[TTSNode] Provider stream cleanup was unavailable")
        return

    task = asyncio.create_task(_run_close())
    done, _ = await asyncio.wait({task}, timeout=timeout_seconds)
    if task in done:
        _consume_background_task(task)
    else:
        task.add_done_callback(_consume_background_task)


async def _next_chunk_or_interrupt(
    stream: Any,
    interrupt_signal: asyncio.Event,
    *,
    timeout_seconds: float,
) -> bytes:
    """Wait for the next provider chunk while remaining promptly interruptible."""
    if interrupt_signal.is_set():
        raise _UserInterruptedError

    async def _read_next() -> bytes:
        return await anext(stream)

    next_task = asyncio.create_task(_read_next())
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError("TTS stream idle timeout")
            done, _ = await asyncio.wait(
                {next_task},
                timeout=min(remaining, 0.05),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if interrupt_signal.is_set():
                raise _UserInterruptedError
            if done:
                return next_task.result()
    finally:
        pending = [next_task] if not next_task.done() else []
        if pending:
            await _settle_cancelled_task(next_task)


async def _synthesize_streaming(
    *,
    state: AgentState,
    config: RunnableConfig | None,
    tts_engine: Any,
    clean_text: str,
    emotion: str,
    instruction: str,
    timeout_seconds: float,
    provider: str,
    started: float,
) -> dict[str, Any]:
    delivery, to = _stream_delivery(state, config)
    if delivery is None:
        raise RuntimeError("Socket.IO is required for progressive TTS")

    stream_id = str(uuid4())
    sequence = -1
    stream_started = False
    first_audio_at: float | None = None
    pcm_bytes = 0
    synthesis_kwargs = {"emotion": emotion, "instruction": instruction}
    performance = validated_performance_payload(state.get("performance_plan"))
    interrupt_signal = get_interrupt_handler().get_signal(state["session_id"])

    retry_delays = _RETRYABLE_REMOTE_STREAM_DELAYS_SECONDS
    for attempt in range(len(retry_delays) + 1):
        stream: Any | None = None
        try:
            stream = aiter(
                tts_engine.synthesize_stream(
                    clean_text,
                    **synthesis_kwargs,
                )
            )
            while True:
                try:
                    chunk = await _next_chunk_or_interrupt(
                        stream,
                        interrupt_signal,
                        timeout_seconds=timeout_seconds,
                    )
                except StopAsyncIteration:
                    break
                if not isinstance(chunk, bytes) or not chunk or len(chunk) % 2:
                    raise RuntimeError("TTS stream returned invalid PCM")
                pcm_bytes += len(chunk)
                if not stream_started:
                    first_audio_at = time.perf_counter()
                    start_payload: dict[str, Any] = {
                        "stream_id": stream_id,
                        "format": "pcm_s16le",
                        "sample_rate": int(getattr(tts_engine, "sample_rate", 24000)),
                        "channels": 1,
                        "emotion": emotion,
                    }
                    if performance is not None:
                        start_payload["performance"] = performance
                    await delivery.emit(
                        "chat",
                        "audio_stream_start",
                        start_payload,
                        to=to,
                    )
                    stream_started = True
                sequence += 1
                await delivery.emit(
                    "chat",
                    "audio_stream_chunk",
                    {
                        "stream_id": stream_id,
                        "sequence": sequence,
                        "audio_data": base64.b64encode(chunk).decode("ascii"),
                    },
                    to=to,
                )
            if interrupt_signal.is_set():
                raise _UserInterruptedError
            if sequence < 0:
                raise RuntimeError("TTS stream completed without audio")
        except _UserInterruptedError:
            await _close_async_stream(
                stream,
                timeout_seconds=_INTERRUPT_CLEANUP_GRACE_SECONDS,
            )
            if stream_started:
                try:
                    await _emit_stream_end(
                        delivery,
                        to=to,
                        stream_id=stream_id,
                        final_sequence=sequence,
                        status="cancelled",
                        reason="cancelled",
                    )
                except Exception:
                    logger.warning(
                        "[{}] [TTSNode] Failed to emit interrupted terminal stream event",
                        state.get("session_id", "unknown"),
                    )
            log_timing(
                state,
                "tts.synthesize",
                (time.perf_counter() - started) * 1000,
                "skipped:interrupted",
            )
            return {
                "tts_audio": None,
                "media_status": MediaStatus("skipped", "interrupted", provider, False),
                "metadata": {
                    **state.get("metadata", {}),
                    "tts_provider": provider,
                    "media_status": "skipped",
                    "interruption_reason": "interrupted",
                    "audio_streamed": stream_started,
                    **({"audio_stream_id": stream_id} if stream_started else {}),
                },
            }
        except asyncio.CancelledError:
            await _close_async_stream(
                stream,
                timeout_seconds=_INTERRUPT_CLEANUP_GRACE_SECONDS,
            )
            if stream_started:
                try:
                    await _emit_stream_end(
                        delivery,
                        to=to,
                        stream_id=stream_id,
                        final_sequence=sequence,
                        status="cancelled",
                        reason="cancelled",
                    )
                except Exception:
                    logger.warning(
                        "[{}] [TTSNode] Failed to emit cancelled terminal stream event",
                        state.get("session_id", "unknown"),
                    )
            raise
        except Exception as exc:
            await _close_async_stream(stream)
            retryable_remote = isinstance(exc, RemoteTTSError) and exc.retryable
            should_retry = not stream_started and (
                attempt == 0 or (retryable_remote and attempt < len(retry_delays))
            )
            if should_retry:
                logger.warning(
                    "[{}] [TTSNode] Streaming TTS failed before first chunk; retrying same voice",
                    state.get("session_id", "unknown"),
                )
                if retryable_remote:
                    await asyncio.sleep(retry_delays[attempt])
                continue
            if stream_started:
                try:
                    await _emit_stream_end(
                        delivery,
                        to=to,
                        stream_id=stream_id,
                        final_sequence=sequence,
                        status="failed",
                        reason="timeout" if isinstance(exc, TimeoutError) else "provider_error",
                    )
                except Exception:
                    logger.warning(
                        "[{}] [TTSNode] Failed to emit terminal stream event",
                        state.get("session_id", "unknown"),
                    )
            raise
        else:
            await _close_async_stream(stream)
            await _emit_stream_end(
                delivery,
                to=to,
                stream_id=stream_id,
                final_sequence=sequence,
                status="completed",
            )
            completed_at = time.perf_counter()
            actual_provider = _actual_tts_provider(tts_engine, provider)
            sample_rate = int(getattr(tts_engine, "sample_rate", 24000))
            audio_seconds = pcm_bytes / (2 * sample_rate)
            first_audio_ms = ((first_audio_at or completed_at) - started) * 1000
            rtf = (completed_at - started) / audio_seconds if audio_seconds > 0 else 0.0
            log_timing(
                state,
                "tts.synthesize",
                (completed_at - started) * 1000,
                "ready:streamed",
            )
            return {
                "tts_audio": None,
                "media_status": MediaStatus("ready", provider=actual_provider),
                "metadata": {
                    **state.get("metadata", {}),
                    "tts_provider": actual_provider,
                    "tts_first_audio_ms": first_audio_ms,
                    "tts_rtf": rtf,
                    "media_status": "ready",
                    "audio_streamed": True,
                    "audio_stream_id": stream_id,
                },
            }

    raise AssertionError("stream retry loop must return or raise")


def _actual_tts_provider(tts_engine: Any, default: str) -> str:
    value = getattr(tts_engine, "actual_provider", None)
    return value if isinstance(value, str) and value else default


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
    golden = getattr(system, "runtime_profile", None) in {
        "smoke",
        "production",
        "golden",
    }
    provider, provider_type, identity_matches = _resolve_provider_identity(
        service_context,
        tts_engine,
    )
    if golden and (provider_type == "mock" or provider == "mock"):
        return {
            "tts_audio": None,
            "media_status": MediaStatus("degraded", "mock_forbidden", provider, False),
        }
    if golden and not identity_matches:
        return {
            "tts_audio": None,
            "media_status": MediaStatus(
                "degraded",
                "identity_mismatch",
                provider,
                False,
            ),
        }

    # Strip emoji and emotion tags before TTS so the voice doesn't read them aloud
    clean_text = _clean_text_for_tts(response_text)
    emotion = str(state.get("emotion") or "neutral")
    synthesis_kwargs: dict[str, Any] = {}
    if getattr(tts_engine, "supports_emotion_instructions", False) is True:
        synthesis_kwargs = {
            "emotion": emotion,
            "instruction": build_emotion_instruction(emotion),
        }
    logger.debug(
        f"[{session_id}] [TTSNode] Text length: {len(response_text)} chars → {len(clean_text)} chars (cleaned)"
    )

    try:
        started = time.perf_counter()
        timeout_seconds = (
            float(getattr(system, "golden_tts_timeout_seconds", 20.0)) if golden else 300.0
        )
        if getattr(tts_engine, "supports_streaming", False) is True:
            return await _synthesize_streaming(
                state=state,
                config=config,
                tts_engine=tts_engine,
                clean_text=clean_text,
                emotion=emotion,
                instruction=build_emotion_instruction(emotion),
                timeout_seconds=timeout_seconds,
                provider=provider,
                started=started,
            )
        audio = await asyncio.wait_for(
            tts_engine.synthesize(clean_text, **synthesis_kwargs), timeout=timeout_seconds
        )
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
    except RemoteTTSError as e:
        category = e.category
        log_timing(
            state,
            "tts.synthesize",
            (time.perf_counter() - started) * 1000,
            f"degraded:{category}",
        )
        logger.warning(
            "[{}] [TTSNode] Remote TTS degraded: category={}, retryable={}",
            session_id,
            category,
            e.retryable,
        )
        await log_node_error(session_id, "tts_node", category, duration_ms=0)
        return {
            "tts_audio": None,
            "media_status": MediaStatus(
                "degraded",
                category,
                provider,
                e.retryable,
            ),
            "metadata": {
                **state.get("metadata", {}),
                "tts_provider": provider,
                "media_status": "degraded",
                "degradation_reason": category,
            },
        }
    except Exception as e:
        log_timing(
            state,
            "tts.synthesize",
            (time.perf_counter() - started) * 1000,
            "degraded:provider_error",
        )
        logger.warning(
            "[{}] [TTSNode] TTS failed: error_type={}",
            session_id,
            type(e).__name__,
        )
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

    provider = _actual_tts_provider(tts_engine, provider)
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
