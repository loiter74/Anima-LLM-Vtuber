#!/usr/bin/env python3
"""Focused real-Qwen Alice smoke; exits non-zero on any missing media evidence."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import wave
from uuid import uuid4

import audioop

from animetta.config.app import AppConfig
from animetta.services.tts.qwen3_tts import Qwen3TTSTTS


def build_evidence(audio: bytes, provider: Qwen3TTSTTS, task_id: str) -> dict:
    volumes = _wav_volumes(audio)
    return {
        "ok": bool(audio) and bool(volumes),
        "task_id": task_id,
        "audio_bytes": len(audio),
        "volume_samples": len(volumes),
        "volume_nonzero": sum(value > 0.001 for value in volumes),
        "live2d": {"task_id": task_id, "expression": "neutral"},
        "provider": {
            "type": "qwen3", "class": type(provider).__name__,
            "model": provider.model, "voice": "alice_vc",
            "preload": provider.preload_status["state"],
        },
    }


def _wav_volumes(audio: bytes) -> list[float]:
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            width = source.getsampwidth()
            maximum = float((1 << (8 * width - 1)) - 1)
            result = []
            while chunk := source.readframes(1024):
                result.append(min(1.0, audioop.rms(chunk, width) / maximum))
            return result
    except (EOFError, wave.Error):
        return []


async def run(text: str) -> dict:
    config = AppConfig.load()
    if config.system.runtime_profile != "golden" or config.tts is None:
        raise RuntimeError("golden Qwen configuration is required")
    provider = Qwen3TTSTTS.from_config(config.tts)
    try:
        await provider.preload()
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
