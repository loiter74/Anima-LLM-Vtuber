#!/usr/bin/env python3
"""Focused real-Qwen Alice smoke; exits non-zero on any missing media evidence."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import wave
from uuid import uuid4

from animetta.config.manifest import load_effective_config
from animetta.config.providers.tts.remote import RemoteTTSConfig
from animetta.services.tts.remote_tts import RemoteTTS


def build_evidence(audio: bytes, provider: RemoteTTS, task_id: str) -> dict:
    volumes = _wav_volumes(audio)
    volume_nonzero = sum(value > 0.001 for value in volumes)
    return {
        "ok": bool(audio) and bool(volumes) and volume_nonzero > 0,
        "task_id": task_id,
        "audio_bytes": len(audio),
        "volume_samples": len(volumes),
        "volume_nonzero": volume_nonzero,
        "live2d": {"task_id": task_id, "expression": "neutral"},
        "provider": {
            "type": "remote",
            "class": type(provider).__name__,
            "provider": provider.provider,
            "model": provider.model,
            "voice": provider.voice,
            "resolved": provider.resolved_identity,
        },
    }


def _wav_volumes(audio: bytes) -> list[float]:
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            width = source.getsampwidth()
            maximum = float((1 << (8 * width - 1)) - 1)
            result = []
            while chunk := source.readframes(1024):
                result.append(min(1.0, _pcm_rms(chunk, width) / maximum))
            return result
    except (EOFError, wave.Error):
        return []


def _pcm_rms(chunk: bytes, width: int) -> float:
    """Return RMS amplitude for little-endian signed PCM without ``audioop``."""
    if width not in {1, 2, 3, 4}:
        raise ValueError(f"unsupported PCM sample width: {width}")
    sample_count = len(chunk) // width
    if sample_count == 0:
        return 0.0
    squares = sum(
        int.from_bytes(chunk[offset : offset + width], "little", signed=True) ** 2
        for offset in range(0, sample_count * width, width)
    )
    return math.sqrt(squares / sample_count)


async def run(text: str) -> dict:
    config = load_effective_config(profile="production")
    tts_config = config.typed_provider("tts")
    if not isinstance(tts_config, RemoteTTSConfig):
        raise RuntimeError("production RemoteTTS configuration is required")
    provider = RemoteTTS.from_config(tts_config)
    try:
        await provider.check_readiness()
        task_id = str(uuid4())
        audio = await provider.synthesize(text)
        if not isinstance(audio, bytes):
            raise RuntimeError("Qwen smoke requires in-memory WAV bytes")
        evidence = build_evidence(audio, provider, task_id)
        if not evidence["ok"] or evidence["live2d"]["task_id"] != task_id:
            raise RuntimeError("Qwen Alice smoke evidence is incomplete")
        return evidence
    finally:
        await provider.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="旅人，欢迎来到 Anima 的酒馆。")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.text)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
