#!/usr/bin/env python3
"""Run the real DeepSeek/MiMo smoke gate and emit sanitized evidence."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import platform
import time
import urllib.request
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from animetta.config.manifest import load_effective_config
from animetta.config.providers.asr.mimo import MimoASRConfig
from animetta.config.providers.tts.mimo import MimoTTSConfig
from animetta.config.providers.vad.mimo import MimoVADConfig
from animetta.services.asr.mimo_asr import MimoASR
from animetta.services.llm.openai_llm import OpenAILLM
from animetta.services.tts.mimo_tts import MimoTTS
from animetta.services.vad.mimo_vad import MimoVAD

SERVICE_CATEGORIES = ("llm", "asr", "tts", "vad")
IDENTITY_FIELDS = ("type", "provider", "model", "voice")


class SmokeGateError(RuntimeError):
    """A release-blocking real-profile smoke invariant failed."""


def validate_readiness_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the public readiness contract and return a sanitized summary."""
    if payload.get("ready") is not True or payload.get("profile") != "smoke":
        raise SmokeGateError("smoke_runtime_not_ready")
    components = payload.get("components")
    if not isinstance(components, dict):
        raise SmokeGateError("readiness_components_missing")

    providers: dict[str, dict[str, str | None]] = {}
    for category in SERVICE_CATEGORIES:
        component = components.get(category)
        if not isinstance(component, dict) or component.get("ready") is not True:
            raise SmokeGateError(f"provider_not_ready:{category}")
        configured = component.get("configured")
        resolved = component.get("resolved")
        if not isinstance(configured, dict) or not isinstance(resolved, dict):
            raise SmokeGateError(f"provider_identity_missing:{category}")
        if any(configured.get(field) != resolved.get(field) for field in IDENTITY_FIELDS):
            raise SmokeGateError(f"provider_identity_mismatch:{category}")
        identity = {field: configured.get(field) for field in IDENTITY_FIELDS}
        if "mock" in json.dumps(identity, ensure_ascii=False).lower():
            raise SmokeGateError(f"mock_provider_observed:{category}")
        providers[category] = identity

    if providers["asr"] == providers["tts"]:
        raise SmokeGateError("asr_tts_rows_conflated")
    return {
        "profile": "smoke",
        "version": payload.get("version"),
        "effective_hash": payload.get("effective_hash"),
        "semantic_hash": payload.get("semantic_hash"),
        "providers": providers,
    }


async def _get_json(url: str) -> dict[str, Any]:
    def read() -> dict[str, Any]:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    value = await asyncio.to_thread(read)
    if not isinstance(value, dict):
        raise SmokeGateError("readiness_payload_invalid")
    return value


def _wav_to_mono(audio: bytes, target_rate: int) -> np.ndarray:
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            source_rate = source.getframerate()
            frames = source.readframes(source.getnframes())
    except (EOFError, wave.Error) as exc:
        raise SmokeGateError("tts_audio_not_wav") from exc
    if width != 2 or channels < 1 or source_rate < 1:
        raise SmokeGateError("tts_wav_format_unsupported")

    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    samples /= 32767.0
    if source_rate != target_rate and samples.size:
        target_size = max(1, round(samples.size * target_rate / source_rate))
        source_axis = np.linspace(0.0, 1.0, samples.size, endpoint=False)
        target_axis = np.linspace(0.0, 1.0, target_size, endpoint=False)
        samples = np.interp(target_axis, source_axis, samples).astype(np.float32)
    return np.clip(samples, -1.0, 1.0)


def _exercise_vad(vad: MimoVAD, audio: bytes) -> dict[str, Any]:
    samples = _wav_to_mono(audio, vad.sample_rate)
    if samples.size == 0 or float(np.max(np.abs(samples))) < 0.01:
        raise SmokeGateError("tts_audio_silent")
    chunk_size = min(samples.size, max(1600, vad.sample_rate // 2))
    loudest_start = int(np.argmax(np.abs(samples)))
    start = min(max(0, loudest_start - chunk_size // 2), samples.size - chunk_size)
    loud = samples[start : start + chunk_size]

    started = False
    final = None
    for _ in range(max(2, vad.min_speech_duration + 1)):
        result = vad.detect_speech(loud)
        started = started or result.is_speech_start
    silence = np.zeros(chunk_size, dtype=np.float32)
    for _ in range(vad.min_silence_duration + 1):
        result = vad.detect_speech(silence)
        if result.is_speech_end:
            final = result
            break
    if not started or final is None or final.speech_detected is not True:
        raise SmokeGateError("mimo_vad_did_not_confirm_speech")
    if final.metadata.get("asr_confirmed") is not True:
        raise SmokeGateError("mimo_vad_asr_confirmation_missing")
    return {
        "speech_start": started,
        "speech_end": True,
        "speech_detected": True,
        "asr_confirmed": True,
        "asr_text_len": final.metadata.get("asr_text_len", 0),
    }


async def run(base_url: str, config_path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    readiness = validate_readiness_payload(
        await _get_json(f"{base_url.rstrip('/')}/ready")
    )
    config = load_effective_config(config_path, profile="smoke")
    if readiness["semantic_hash"] != config.semantic_hash:
        raise SmokeGateError("semantic_hash_mismatch")

    asr_config = config.typed_provider("asr")
    tts_config = config.typed_provider("tts")
    vad_config = config.typed_provider("vad")
    if not isinstance(asr_config, MimoASRConfig):
        raise SmokeGateError("smoke_asr_config_type_mismatch")
    if not isinstance(tts_config, MimoTTSConfig):
        raise SmokeGateError("smoke_tts_config_type_mismatch")
    if not isinstance(vad_config, MimoVADConfig):
        raise SmokeGateError("smoke_vad_config_type_mismatch")

    llm = OpenAILLM.from_config(config.typed_provider("llm"))
    asr = MimoASR.from_config(asr_config)
    tts = MimoTTS.from_config(tts_config)
    vad = MimoVAD.from_config(vad_config)
    timings: dict[str, float] = {}
    try:
        checkpoint = time.perf_counter()
        text = await llm.chat_messages(
            [{"role": "user", "content": "仅回复 smoke-ok"}],
            temperature=0,
            max_tokens=32,
        )
        timings["llm_ms"] = round((time.perf_counter() - checkpoint) * 1000, 2)
        if not isinstance(text, str) or not text.strip():
            raise SmokeGateError("deepseek_empty_text")

        checkpoint = time.perf_counter()
        audio = await tts.synthesize("这是 Animetta 的真实服务回归测试。")
        timings["tts_ms"] = round((time.perf_counter() - checkpoint) * 1000, 2)
        if not isinstance(audio, bytes) or len(audio) < 44:
            raise SmokeGateError("mimo_tts_empty_audio")

        checkpoint = time.perf_counter()
        transcription = await asr.transcribe(audio, audio_format="wav")
        timings["asr_ms"] = round((time.perf_counter() - checkpoint) * 1000, 2)
        if not transcription.strip():
            raise SmokeGateError("mimo_asr_empty_text")

        checkpoint = time.perf_counter()
        vad_result = await asyncio.to_thread(_exercise_vad, vad, audio)
        timings["vad_ms"] = round((time.perf_counter() - checkpoint) * 1000, 2)
    finally:
        await llm.close()
        await asr.close()
        await tts.close()
        await vad.close()

    elapsed = time.perf_counter() - started
    return {
        "status": "passed",
        "profile": readiness["profile"],
        "version": readiness["version"],
        "effective_hash": readiness["effective_hash"],
        "semantic_hash": readiness["semantic_hash"],
        "providers": readiness["providers"],
        "checks": {
            "deepseek_text": {"non_empty": True, "length": len(text)},
            "mimo_tts": {"non_empty": True, "audio_bytes": len(audio)},
            "mimo_asr": {"non_empty": True, "text_length": len(transcription)},
            "mimo_vad": vad_result,
        },
        "timings": timings,
        "duration_seconds": round(elapsed, 3),
        "within_120_seconds": elapsed <= 120,
    }


def _write_evidence(directory: Path, payload: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = directory / f"real-smoke-{stamp}.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost")
    parser.add_argument("--config", type=Path, default=Path("config/animetta.yaml"))
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--evidence-dir", type=Path, default=Path("evidence/real-smoke"))
    args = parser.parse_args()
    initial = {
        "status": "failed",
        "environment": {
            "url": args.url,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "timeout_seconds": args.timeout,
        },
    }
    try:
        async def execute() -> dict[str, Any]:
            async with asyncio.timeout(args.timeout):
                return await run(args.url, args.config)

        payload = {**initial, **asyncio.run(execute())}
    except Exception as exc:
        payload = {
            **initial,
            "failure": {"type": type(exc).__name__, "reason": "real_smoke_failed"},
        }
    path = _write_evidence(args.evidence_dir, payload)
    print(path)
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
