"""Bounded Prometheus projections for composite TTS runtime measurements."""

from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram

    _FAILOVER_TOTAL = Counter(
        "anima_tts_failover_total",
        "TTS requests switched from cloud to local by bounded reason",
        ("reason",),
    )
    _CIRCUIT_TOTAL = Counter(
        "anima_tts_circuit_open_total",
        "TTS primary circuit openings by bounded reason",
        ("reason",),
    )
    _FIRST_AUDIO = Histogram(
        "anima_tts_first_audio_seconds",
        "TTS first PCM latency by actual backend",
        ("backend",),
    )
    _RTF = Histogram(
        "anima_tts_realtime_factor",
        "TTS realtime factor by actual backend",
        ("backend",),
    )
except (ImportError, ValueError):  # pragma: no cover - optional/reloaded registry
    _FAILOVER_TOTAL = _CIRCUIT_TOTAL = _FIRST_AUDIO = _RTF = None

_REASONS = {
    "authentication",
    "billing",
    "connection",
    "empty_audio",
    "identity_mismatch",
    "incompatible_contract",
    "provider_error",
    "timeout",
}
_BACKENDS = {"primary", "fallback"}


def record_failover(reason: str) -> None:
    if _FAILOVER_TOTAL is not None:
        _FAILOVER_TOTAL.labels(reason=_bounded_reason(reason)).inc()


def record_circuit_open(reason: str) -> None:
    if _CIRCUIT_TOTAL is not None:
        _CIRCUIT_TOTAL.labels(reason=_bounded_reason(reason)).inc()


def observe_first_audio(backend: str, seconds: float) -> None:
    if _FIRST_AUDIO is not None:
        _FIRST_AUDIO.labels(backend=_bounded_backend(backend)).observe(seconds)


def observe_rtf(backend: str, rtf: float) -> None:
    if _RTF is not None:
        _RTF.labels(backend=_bounded_backend(backend)).observe(rtf)


def _bounded_reason(reason: str) -> str:
    return reason if reason in _REASONS else "other"


def _bounded_backend(backend: str) -> str:
    return backend if backend in _BACKENDS else "other"
