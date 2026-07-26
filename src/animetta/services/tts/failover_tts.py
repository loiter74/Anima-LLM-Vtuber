"""Cloud-first TTS with first-audio binding and local circuit-breaker fallback."""

from __future__ import annotations

import asyncio
import contextvars
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.tts.failover import FailoverTTSConfig
from animetta.observability.tts_metrics import (
    observe_first_audio,
    observe_rtf,
    record_circuit_open,
    record_failover,
)

from .dashscope_tts import DashScopeRealtimeTTS
from .interface import TTSInterface
from .remote_tts import RemoteTTS, RemoteTTSError

_METRIC_REASONS = {
    "authentication",
    "billing",
    "connection",
    "empty_audio",
    "identity_mismatch",
    "incompatible_contract",
    "provider_error",
    "timeout",
}


def _safe_identity_value(value: Any) -> str | None:
    return str(value) if isinstance(value, (str, int, float)) else None


class FailoverTTSUnavailableError(RuntimeError):
    """Neither configured backend could be preloaded."""


class _EmptyPrimaryAudioError(RemoteTTSError):
    pass


@ProviderRegistry.register_service("tts", "failover")
class FailoverTTS(TTSInterface):
    """Bind an utterance to cloud after first audio; otherwise use local."""

    supports_streaming = True
    provider_identity = "failover"
    model = "dashscope+qwen3-tts-1.7b"
    voice = "Seren+tosaka-rin-cn"

    def __init__(
        self,
        *,
        primary: TTSInterface,
        fallback: TTSInterface,
        cooldown_seconds: float = 300.0,
        primary_pre_audio_retries: int = 1,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.cooldown_seconds = cooldown_seconds
        self.primary_pre_audio_retries = primary_pre_audio_retries
        self._clock = clock or time.monotonic
        self._state_lock = asyncio.Lock()
        self._circuit_state = "closed"
        self._opened_at: float | None = None
        self._primary_ready = False
        self._fallback_ready = False
        self._primary_error_category: str | None = "not_preloaded"
        self._fallback_error_category: str | None = "not_preloaded"
        self._closed = False
        self._switch_counts: dict[str, int] = {}
        self._last_first_audio_seconds: dict[str, float] = {}
        self._last_rtf: dict[str, float] = {}
        self._actual_backend: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            "failover_tts_actual_backend", default=None
        )

    @classmethod
    def from_config(
        cls,
        config: FailoverTTSConfig,
        **kwargs: Any,
    ) -> FailoverTTS:
        primary = kwargs.get("primary") or DashScopeRealtimeTTS.from_config(config.primary)
        fallback = kwargs.get("fallback") or RemoteTTS.from_config(config.fallback)
        return cls(
            primary=primary,
            fallback=fallback,
            cooldown_seconds=config.cooldown_seconds,
            primary_pre_audio_retries=config.primary_pre_audio_retries,
            clock=kwargs.get("clock"),
        )

    async def preload(self) -> None:
        primary_result, fallback_result = await asyncio.gather(
            self._preload_child(self.primary),
            self._preload_child(self.fallback),
        )
        self._primary_ready, self._primary_error_category = primary_result
        self._fallback_ready, self._fallback_error_category = fallback_result
        if not self._primary_ready:
            self._circuit_state = "open"
            self._opened_at = self._clock()
        if not self._primary_ready and not self._fallback_ready:
            raise FailoverTTSUnavailableError("No TTS backend is ready")

    @staticmethod
    async def _preload_child(
        child: TTSInterface,
    ) -> tuple[bool, str | None]:
        preload = getattr(child, "preload", None)
        if not callable(preload):
            return True, None
        try:
            await preload()
        except BaseException as error:
            return False, FailoverTTS._error_category(error)
        return True, None

    async def synthesize_stream(
        self,
        text: str,
        **kwargs: Any,
    ) -> AsyncIterator[bytes]:
        use_primary, probe = await self._select_primary()
        if not use_primary:
            async for chunk in self._fallback_stream(text, kwargs):
                yield chunk
            return

        last_error: BaseException | None = None
        request_started = self._clock()
        attempts = self.primary_pre_audio_retries + 1
        for attempt in range(attempts):
            stream = self._child_stream(self.primary, text, kwargs)
            try:
                first_chunk = await anext(stream)
            except StopAsyncIteration:
                last_error = _EmptyPrimaryAudioError(
                    "Primary TTS returned no audio",
                    category="empty_audio",
                    retryable=True,
                )
            except asyncio.CancelledError:
                await self._close_stream(stream)
                if probe:
                    await self._record_primary_failure("cancelled")
                raise
            except BaseException as error:
                last_error = error
            else:
                self._actual_backend.set("primary")
                first_audio_seconds = max(0.0, self._clock() - request_started)
                self._observe_first_audio("primary", first_audio_seconds)
                pcm_bytes = len(first_chunk)
                yield first_chunk
                try:
                    async for chunk in stream:
                        pcm_bytes += len(chunk)
                        yield chunk
                except asyncio.CancelledError:
                    raise
                except BaseException as error:
                    await self._record_primary_failure(self._error_category(error))
                    raise
                else:
                    self._observe_rtf(
                        "primary",
                        request_started=request_started,
                        pcm_bytes=pcm_bytes,
                    )
                    if probe:
                        await self._record_primary_success()
                    return
                finally:
                    await self._close_stream(stream)

            await self._close_stream(stream)
            if attempt + 1 < attempts and last_error is not None and self._is_retryable(last_error):
                continue
            break

        category = self._error_category(last_error)
        await self._record_primary_failure(category)
        self._record_switch(category)
        async for chunk in self._fallback_stream(text, kwargs):
            yield chunk

    async def _fallback_stream(
        self,
        text: str,
        kwargs: dict[str, Any],
    ) -> AsyncIterator[bytes]:
        self._actual_backend.set("fallback")
        started = self._clock()
        first = True
        pcm_bytes = 0
        try:
            async for chunk in self._child_stream(self.fallback, text, kwargs):
                pcm_bytes += len(chunk)
                if first:
                    self._observe_first_audio(
                        "fallback",
                        max(0.0, self._clock() - started),
                    )
                    first = False
                yield chunk
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            await self._record_fallback_failure(self._error_category(error))
            raise
        if first:
            empty_audio_error = FailoverTTSUnavailableError("Fallback TTS returned no audio")
            await self._record_fallback_failure("empty_audio")
            raise empty_audio_error
        await self._record_fallback_success()
        self._observe_rtf(
            "fallback",
            request_started=started,
            pcm_bytes=pcm_bytes,
        )

    @staticmethod
    def _child_stream(
        child: TTSInterface,
        text: str,
        kwargs: dict[str, Any],
    ) -> AsyncIterator[bytes]:
        stream_method = getattr(child, "synthesize_stream", None)
        if not callable(stream_method):
            raise FailoverTTSUnavailableError("Configured TTS backend cannot stream")
        return stream_method(text, **kwargs)

    @staticmethod
    async def _close_stream(stream: AsyncIterator[bytes]) -> None:
        close = getattr(stream, "aclose", None)
        if callable(close):
            await close()

    async def synthesize(
        self,
        text: str,
        output_path: str | Path | None = None,
        **kwargs: Any,
    ) -> bytes | str:
        use_primary, probe = await self._select_primary()
        result: bytes | str
        if use_primary:
            error: BaseException | None = None
            for attempt in range(self.primary_pre_audio_retries + 1):
                try:
                    result = await self.primary.synthesize(text, None, **kwargs)
                except asyncio.CancelledError:
                    if probe:
                        await self._record_primary_failure("cancelled")
                    raise
                except BaseException as caught:
                    error = caught
                    if attempt < self.primary_pre_audio_retries and self._is_retryable(caught):
                        continue
                    break
                else:
                    self._actual_backend.set("primary")
                    if probe:
                        await self._record_primary_success()
                    return self._write_if_requested(result, output_path)
            category = self._error_category(error)
            await self._record_primary_failure(category)
            self._record_switch(category)

        try:
            result = await self.fallback.synthesize(text, None, **kwargs)
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            await self._record_fallback_failure(self._error_category(error))
            raise
        await self._record_fallback_success()
        self._actual_backend.set("fallback")
        return self._write_if_requested(result, output_path)

    @staticmethod
    def _write_if_requested(
        result: bytes | str,
        output_path: str | Path | None,
    ) -> bytes | str:
        if output_path is None:
            return result
        if not isinstance(result, bytes):
            raise RuntimeError("TTS backend returned a path without an output request")
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(result)
        return str(path)

    async def _select_primary(self) -> tuple[bool, bool]:
        async with self._state_lock:
            if self._circuit_state == "closed":
                return self._primary_ready, False
            if self._circuit_state == "half_open":
                return False, False
            assert self._opened_at is not None
            if self._clock() - self._opened_at < self.cooldown_seconds:
                return False, False
            self._circuit_state = "half_open"
            return True, True

    async def _record_primary_failure(self, category: str) -> None:
        async with self._state_lock:
            self._primary_error_category = category
            self._circuit_state = "open"
            self._opened_at = self._clock()
        reason = self._metric_reason(category)
        record_circuit_open(reason)

    async def _record_primary_success(self) -> None:
        async with self._state_lock:
            self._primary_error_category = None
            self._primary_ready = True
            self._circuit_state = "closed"
            self._opened_at = None

    async def _record_fallback_failure(self, category: str) -> None:
        async with self._state_lock:
            self._fallback_ready = False
            self._fallback_error_category = category

    async def _record_fallback_success(self) -> None:
        async with self._state_lock:
            self._fallback_ready = True
            self._fallback_error_category = None

    @staticmethod
    def _error_category(error: BaseException | None) -> str:
        category = getattr(error, "category", None)
        if isinstance(category, str) and category:
            return category
        if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
            return "timeout"
        return "provider_error"

    @staticmethod
    def _is_retryable(error: BaseException) -> bool:
        retryable = getattr(error, "retryable", None)
        if isinstance(retryable, bool):
            return retryable
        return isinstance(error, (TimeoutError, ConnectionError))

    @staticmethod
    def _metric_reason(category: str) -> str:
        return category if category in _METRIC_REASONS else "other"

    def _record_switch(self, category: str) -> None:
        reason = self._metric_reason(category)
        self._switch_counts[reason] = self._switch_counts.get(reason, 0) + 1
        record_failover(reason)

    def _observe_first_audio(self, backend: str, seconds: float) -> None:
        self._last_first_audio_seconds[backend] = seconds
        observe_first_audio(backend, seconds)

    def _observe_rtf(
        self,
        backend: str,
        *,
        request_started: float,
        pcm_bytes: int,
    ) -> None:
        audio_seconds = pcm_bytes / (2 * self.sample_rate)
        if audio_seconds <= 0:
            return
        rtf = max(0.0, self._clock() - request_started) / audio_seconds
        self._last_rtf[backend] = rtf
        observe_rtf(backend, rtf)

    def metrics_snapshot(self) -> dict[str, Any]:
        return {
            "switch_reasons": dict(self._switch_counts),
            "first_audio_seconds": dict(self._last_first_audio_seconds),
            "rtf": dict(self._last_rtf),
        }

    def readiness_snapshot(self) -> dict[str, Any]:
        now = self._clock()
        remaining = 0.0
        if self._circuit_state == "open" and self._opened_at is not None:
            remaining = max(0.0, self.cooldown_seconds - (now - self._opened_at))
        ready = self._primary_ready or self._fallback_ready
        active = (
            "primary"
            if self._primary_ready and self._circuit_state == "closed"
            else "fallback"
            if self._fallback_ready
            else None
        )
        primary_identity = self._child_identity(self.primary)
        fallback_identity = self._child_identity(self.fallback)
        return {
            "ready": ready,
            "degraded": ready
            and (
                not (self._primary_ready and self._fallback_ready)
                or self._circuit_state != "closed"
            ),
            "active_backend": active,
            "primary": {
                "ready": self._primary_ready,
                "error_category": self._primary_error_category,
                **({"identity": primary_identity} if any(primary_identity.values()) else {}),
            },
            "fallback": {
                "ready": self._fallback_ready,
                "error_category": self._fallback_error_category,
                **({"identity": fallback_identity} if any(fallback_identity.values()) else {}),
            },
            "circuit": {
                "state": self._circuit_state,
                "cooldown_remaining_seconds": remaining,
            },
        }

    @staticmethod
    def _child_identity(child: TTSInterface) -> dict[str, str | None]:
        supplied = getattr(child, "resolved_identity", None)
        if not isinstance(supplied, dict):
            supplied = {}
        provider = supplied.get("provider")
        if provider is None:
            provider = getattr(child, "provider_identity", None)
        if provider is None:
            provider = getattr(child, "provider", None)
        return {
            "type": _safe_identity_value(supplied.get("type")),
            "provider": _safe_identity_value(provider),
            "model": _safe_identity_value(supplied.get("model", getattr(child, "model", None))),
            "voice": _safe_identity_value(supplied.get("voice", getattr(child, "voice", None))),
        }

    @property
    def actual_backend(self) -> str | None:
        return self._actual_backend.get()

    @property
    def actual_provider(self) -> str | None:
        backend = self.actual_backend
        child = (
            self.primary
            if backend == "primary"
            else self.fallback
            if backend == "fallback"
            else None
        )
        if child is None:
            return None
        provider = getattr(child, "provider_identity", None)
        if provider is None:
            provider = getattr(child, "provider", None)
        return str(provider) if provider else None

    @property
    def resolved_identity(self) -> dict[str, Any]:
        snapshot = self.readiness_snapshot()
        return {
            "type": "failover",
            "provider": self.provider_identity,
            "model": None,
            "voice": None,
            "active_backend": snapshot["active_backend"],
        }

    @property
    def audio_format(self) -> str:
        return "pcm_s16le"

    @property
    def sample_rate(self) -> int:
        return 24000

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await asyncio.gather(
            self.primary.close(),
            self.fallback.close(),
            return_exceptions=True,
        )
